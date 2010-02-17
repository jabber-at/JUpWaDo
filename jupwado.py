#!/usr/bin/python -Wignore::DeprecationWarning

import os, sys, time, sqlite3, threading, ConfigParser
from optparse import OptionParser

import xmpp

now = time.time()
stamp = int( now )
resource = time.strftime( '%Y-%m-%d %H:%M:%S', time.localtime(now) )

class request:
	requests = {}
	def handler( conn, packet ):
		frm = packet.getFrom()
		if frm not in request.requests.keys():
			return
		
		request.requests[frm].handle( packet )

		del( request.requests[frm] )
		
	def cleanup():
		try:
			for req in request.requests.values():
				exp = xmpp.Node( 'no-answer-received', {'xmlns': 'urn:ietf:params:xml:ns:xmpp-stanzas' } )
				error = xmpp.Node( 'error', { 'code': 1, 'type': 'cancel' }, payload=[exp] )
				packet = xmpp.Iq( 'error', xmpp.NS_LAST, to = req.jid )
				packet.kids.append( error )
				req.handle( packet )
		finally:
			pass
#			os._exit( 0 )

	handler = staticmethod( handler )
	cleanup = staticmethod( cleanup )

	def __init__( self, path, section ):
		self.path = path
		self.section = section
		self.jid = self.section.strip()
		self.db = os.path.normpath( path + '/' + self.get_filename() )

	def check_env( self ):
		if not os.path.exists( self.path ):
			try:
				os.makedirs( self.path )
			except:
				print( 'Warning: %s: Could not create directory' %(self.path) )
				return False
		
		if os.path.exists( self.db ):
			# test if writable
			if not os.access( self.db, os.R_OK | os.W_OK ):
				print( 'Warning: %s: Cannot access database' %(self.db) )
				return False
		else: # db-file does not exist, create it:
			try:
				conn = sqlite3.connect( self.db )
				c = conn.cursor()
				c.execute( '''CREATE TABLE scans (
					stamp INTEGER PRIMARY KEY,
					online INTEGER NOT NULL,
					value INTEGER DEFAULT NULL,
					error TEXT DEFAULT NULL)''' )
				c.execute( '''CREATE INDEX status ON scans(online)''' )
				conn.commit()
				c.close()
				conn.close()
			except Exception, e:
				print( 'Warning: %s: Error creating database' %(self.db) )
				print e
				return False

		return True
	
	def get_filename( self ):
		s = self.section.strip( '/ ' )
		return s.replace( '/', '_' )

	def handle( self, packet ):
#		print( "Received response for " + self.jid )
		type = packet.getType()

		if type == 'result':
			seconds = packet.kids[0].getAttr( 'seconds' )
			sql = '''INSERT INTO scans(stamp, online, value)
				VALUES(?, ?, ?)'''
			tuple = (stamp, 1, seconds)
			if seconds < 300:
				tuple[1] = (stamp, 0, seconds)
		elif type == 'error':
			for child in packet.getChildren():
				if child.getName() == 'error':
					msg = str(child)
			sql = '''INSERT INTO scans( stamp, online, error)
				VALUES(?, ?, ?)'''
			tuple = (stamp, 0, msg)
		else:
			print( 'Received packet of type ' + type )
			return

		conn = sqlite3.connect( self.db )
		c = conn.cursor()
		c.execute( sql, tuple )
		conn.commit()
		c.close()
		
	def send( self, conn ):
#		print( "Sending uptime request to " + self.jid )
		packet = xmpp.Iq( 'get', xmpp.NS_LAST, to = self.jid )
		conn.send( packet )

class connection( threading.Thread ):
	def __init__( self, con ):
		threading.Thread.__init__( self )
		self.cont = True
		self.con = con
	
	def run( self ):
		self.timer = threading.Timer( 5.0, self.stop )
		self.timer.start()

		self.GoOn()
	
	def stop( self ):
		print( "Stop." )
		self.cont = False
		request.cleanup()

	# infinite loop 1:
	def StepOn( self ):
		if self.cont == False: 
			return 0
		if len(request.requests) == 0:
			self.timer.cancel()
			return 0
	
		try:
			self.con.Process(1)
		except KeyboardInterrupt:
			return 0
		return 1

	# infinite loop 2:
	def GoOn( self ):
		while self.StepOn(): pass

parser = OptionParser()
parser.add_option( '-c', '--config', metavar='FILE',
	help='Location of config-file' )
options, args = parser.parse_args()

config = ConfigParser.ConfigParser( {'path': os.path.expanduser( '~/.jupwado/db/' ) } )
config_files = [ os.path.expanduser( '~/.jupwado/config' ), '/etc/jupwado.conf' ]
if options.config:
	config_files.append( options.config )
config.read( config_files )

if not config.has_section( 'system' ):
	print( 'Error: Config-file has no section "system".' )
	sys.exit(1)

server_list = [ s for s in config.sections() if s != 'system' ]
if len( server_list ) == 0:
	print( 'Error: No servers specified.' )

for server in server_list:
	path = config.get( server, 'path' )
	req = request( path, server )
	if req.check_env():
		request.requests[req.jid] = req
		
my_jid=xmpp.protocol.JID( config.get( 'system', 'jid' ) )
cl=xmpp.Client( my_jid.getDomain(), debug=[] )
cl.connect()
cl.auth( my_jid.getNode(), config.get( 'system', 'pwd' ), resource='jupwado' )
cl.sendInitPresence()
cl.RegisterHandler( 'iq', request.handler, ns=xmpp.NS_LAST )

connection_thread = connection( cl )
connection_thread.start()

for req in request.requests.values():
	req.send( cl )
