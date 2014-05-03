JUpWaDo
=======

The name jupwado stands for "jabber uptime watchdog". This script is a
munin-plugin that reads the database that is filled by jupwado.py. It then
calculates availability for each monitored server as uptime/total_time.

This script is a wildcard-plugin, so you must rename it to something like
jabber_availability_month
or something similar. Currently this script understands the suffix _month, _year
and _day. If no suffix is provided, this will calculate the time from all scans
that are currently logged in the database.
