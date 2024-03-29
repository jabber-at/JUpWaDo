#!/usr/bin/python -Wignore::DeprecationWarning
# -*- coding: utf-8 -*-
#
# The name jupwado stands for "jabber uptime watchdog". This script is a
# munin-plugin that reads the database that is filled by jupwado.py. It then
# calculates availability for each monitored server as uptime/total_time.
#
# This script is a wildcard-plugin, so you must rename it to something like
# jabber_availability_month
# or something similar. Currently this script understands the suffix _month, _year
# and _day. If no suffix is provided, this will calculate the time from all scans
# that are currently logged in the database.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import ConfigParser
import os
import sqlite3
import sys
import threading
import time

from optparse import OptionParser

import xmpp

now = time.time()
stamp = int(now)
resource = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))


class request:
    requests = {}

    def handler(conn, packet):
        frm = packet.getFrom()
        if frm not in request.requests.keys():
            return

        if request.requests[frm].handle(packet):
            del(request.requests[frm])

    def cleanup():
        for req in request.requests.values():
            try:
                req.handle_offline('no answer at all received!')
            except:
                pass

    handler = staticmethod(handler)
    cleanup = staticmethod(cleanup)

    def __init__(self, path, section, threshold):
        self.path = path
        self.section = section
        self.jid = self.section.strip()
        self.db = os.path.normpath(path + '/' + self.get_filename())
        self.threshold = threshold

    def check_env(self):
        if not os.path.exists(self.path):
            try:
                os.makedirs(self.path)
            except:
                print('Warning: %s: Could not create directory' % (self.path))
                return False

        if os.path.exists(self.db):
            # test if writable
            if not os.access(self.db, os.R_OK | os.W_OK):
                print('Warning: %s: Cannot access database' % (self.db))
                return False
        else:  # db-file does not exist, create it:
            try:
                conn = sqlite3.connect(self.db)
                c = conn.cursor()
                c.execute('''CREATE TABLE scans (
                    stamp INTEGER PRIMARY KEY,
                    online INTEGER NOT NULL,
                    value INTEGER DEFAULT NULL,
                    error TEXT DEFAULT NULL)''')
                c.execute('''CREATE INDEX status ON scans(online)''')
                conn.commit()
                c.close()
                conn.close()
            except Exception, e:
                print('Warning: %s: Error creating database' % (self.db))
                print e
                return False

        return True

    def get_filename(self):
        s = self.section.strip('/ ')
        return s.replace('/', '_')

    def handle(self, packet):
        typ = packet.getType()

        if typ == 'result':
            seconds = packet.kids[0].getAttr('seconds')
            self.handle_online(seconds)
        elif typ == 'error':
            self.handle_offline(packet.getError())
        else:
            print('Received packet of type ' + typ)
            return False

        return True

    def handle_online(self, seconds):
        sql = '''INSERT INTO scans(stamp, online, value)
            VALUES(?, ?, ?)'''
        values = (stamp, 1, seconds)
        if seconds < self.threshold:
            values[1] = (stamp, 0, seconds)
        self.insert(sql, values)

    def handle_offline(self, error):
        sql = '''INSERT INTO scans(stamp, online, error)
            VALUES(?, ?, ?)'''
        self.insert(sql, (stamp, 0, error))

    def insert(self, sql, tuple):
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute(sql, tuple)
        conn.commit()
        c.close()

    def send(self, conn):
#        print("Sending uptime request to " + self.jid)
        packet = xmpp.Iq('get', xmpp.NS_LAST, to=self.jid)
        conn.send(packet)


class connection(threading.Thread):
    def __init__(self, con, timeout):
        threading.Thread.__init__(self)
        self.timer = threading.Timer(timeout, self.stop)
        self.cont = True
        self.con = con

    def run(self):
        self.timer.start()

        # this loops until all packets are processed
        while self.StepOn():
            pass

    def stop(self):
        self.cont = False
        request.cleanup()

    def StepOn(self):
        if not self.cont:
            return 0
        if len(request.requests) == 0:
            self.timer.cancel()
            return 0

        try:
            self.con.Process(1)
        except KeyboardInterrupt:
            return 0
        return 1

parser = OptionParser()
parser.add_option('-c', '--config', metavar='FILE', help='Location of config-file')
parser.add_option(
    '-t', '--threshold', metavar='SECS', type="int", default=300,
    help='''Uptimes below this threshold will be considered as "Was offline since the last scan
and will be logged as offline. Usually this time should correspond to how often this script is
executed. [default: %default (= five minutes)]''')
parser.add_option('--timeout', metavar='SECS', type="int", default=15,
                  help='Timeout after SECS seconds. [default: %default]')
options, args = parser.parse_args()

config = ConfigParser.ConfigParser({'path': os.path.expanduser('~/.jupwado/db/')})
config_files = [os.path.expanduser('~/.jupwado/config'), '/etc/jupwado.conf']
if options.config:
    config_files.append(options.config)
config.read(config_files)

if not config.has_section('system'):
    print('Error: Config-file has no section "system".')
    sys.exit(1)

server_list = [s for s in config.sections() if s != 'system']
if len(server_list) == 0:
    print('Error: No servers specified.')

for server in server_list:
    path = config.get(server, 'path')
    req = request(path, server, options.threshold)
    if req.check_env():
        request.requests[req.jid] = req

my_jid = xmpp.protocol.JID(config.get('system', 'jid'))
cl = xmpp.Client(my_jid.getDomain(), debug=[])
cl.connect()
if cl.connected == '':
    print("Error: %s: Cannot connect to server" % (my_jid.getDomain()))
    if my_jid.getDomain() in request.requests.keys():
        request.requests[my_jid.getDomain()].handle_offline('Could not connect to server')
    sys.exit()

# authenticate:
x = cl.auth(my_jid.getNode(), config.get('system', 'pwd'), resource=resource)
if x is None:
    print("Error: Cannot authenticate with user/pass provided in config-file.")
    sys.exit(1)

cl.sendInitPresence(0)
cl.RegisterHandler('iq', request.handler, ns=xmpp.NS_LAST)
connection_thread = connection(cl, options.timeout)
connection_thread.start()

for req in request.requests.values():
    req.send(cl)
