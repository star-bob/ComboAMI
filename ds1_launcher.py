#!/usr/bin/env python
### Script provided by DataStax.

import grp
import os
import pwd
import subprocess
import shlex
import time
import urllib2

import logger
import conf

def initial_configurations():
    # Begin configuration this is only run once in Public Packages

    if not conf.get_config("AMI", "CurrentStatus"):
        # Configure DataStax variables
        try:
            import ds2_configure
            ds2_configure.run()
        except:
            conf.set_config("AMI", "Error", "Exception seen in %s. Please check ~/datastax_ami/ami.log for more info." % 'ds1_launcher.py')

            logger.exception('ds1_launcher.py')


        # Change permission back to being ubuntu's and cassandra's
        logger.exe('sudo chown -hR ubuntu:ubuntu /home/ubuntu')
        logger.exe('sudo chown -hR cassandra:cassandra /raid0/cassandra', False)
        logger.exe('sudo chown -hR cassandra:cassandra /mnt/cassandra', False)

        # Ensure permissions
        directory_list = [
            ('/home/ubuntu', 'ubuntu', 'ubuntu'),
            ('/raid0/cassandra', 'cassandra', 'cassandra'),
            ('/mnt/cassandra', 'cassandra', 'cassandra')
        ]

        for directory in directory_list:
            if os.path.isdir(directory[0]):
                logger.info('Checking permissions for: %s' % directory[0])
                attempt = 0
                max_attempts = 10
                permissions_set = False

                while attempt < max_attempts:
                    logger.info('Attempt #%s' % attempt)
                    stat_info = os.stat(directory[0])
                    uid = stat_info.st_uid
                    gid = stat_info.st_gid

                    user = pwd.getpwuid(uid)[0]
                    group = grp.getgrgid(gid)[0]

                    if user == directory[1] and group == directory[2]:
                        permissions_set = True
                        break

                    attempt += 1
                    time.sleep(1)

                if not permissions_set:
                    logger.warn('Permissions not set correctly. Please run manually:')
                    logger.warn('sudo chown -hR %s:%s %s' % (directory[1], directory[2], directory[0]))
                    logger.warn('sudo service dse restart')
                else:
                    logger.info('Permissions set for %s as %s:%s' % (directory[0], user, group))

    else:
        logger.info('Skipping initial configurations.')

def write_bin_tools():
    with open('/usr/bin/datastax_support', 'w') as f:
        f.write("""#!/usr/bin/env python\nprint '''DataStax Support Links:

        Cassandra Cluster Launcher:
            https://github.com/joaquincasares/cassandralauncher

        Documentation:
            http://www.datastax.com/docs

        AMI:
            http://www.datastax.com/ami

        Cassandra client libraries:
            http://www.datastax.com/download/clientdrivers

        Support Forums:
            http://www.datastax.com/support-forums

        For quick support, visit:
            IRC: #cassandra channel on irc.freenode.net
        '''
        """)

    with open('/usr/bin/datastax_demos', 'w') as f:
        f.write("""#!/usr/bin/env python\nprint '''DataStax Demo Links:

        Portfolio (Hive) Demo:
            http://www.datastax.com/demos/portfolio
        Pig Demo:
            http://www.datastax.com/demos/pig
        Wikipedia (Solr) Demo:
            http://www.datastax.com/demos/wikipedia
        Logging (Solr) Demo:
            http://www.datastax.com/demos/logging
        Sqoop Demo:
            http://www.datastax.com/demos/sqoop
        '''
        """)

    with open('/usr/bin/datastax_tools', 'w') as f:
        f.write("""#!/usr/bin/env python\nprint '''Installed DSE/C Tools:

        Nodetool:
            nodetool --help
        DSEtool:
            dsetool --help
        Cli:
            cassandra-cli -h `hostname`
        CQL Shell:
            cqlsh
        Hive:
            dse hive (on Analytic nodes)
        Pig:
            dse pig (on Analytic nodes)
        '''
        """)

    os.chmod('/usr/bin/datastax_support', 0755)
    os.chmod('/usr/bin/datastax_demos', 0755)
    os.chmod('/usr/bin/datastax_tools', 0755)

def restart_tasks():
    logger.info("AMI Type: " + str(conf.get_config("AMI", "Type")))

    # Mount all attached drives
    logger.exe('sudo mount -a')

    # Disable swap
    logger.exe('sudo swapoff --all')

    # Ensure the correct blockdev readahead since this sometimes resets after restarts
    if conf.get_config('AMI', 'raid_readahead'):
        logger.exe('sudo blockdev --setra %s /dev/md0' % (conf.get_config('AMI', 'raid_readahead')), expectError=True)

def wait_for_seed():
    # Wait for the seed node to come online
    req = urllib2.Request('http://169.254.169.254/latest/meta-data/local-ipv4')
    internalip = urllib2.urlopen(req).read()

    if internalip != conf.get_config("AMI", "LeadingSeed"):
        logger.info("Waiting for seed node to come online...")

        d = dict(os.environ)
        d["HOST"] = conf.get_config("AMI", "LeadingSeed")
        wait_script = "python /home/ubuntu/datastax_ami/wait_for_first_node.sh"
        subprocess.Popen(shlex.split(wait_script), stderr=subprocess.PIPE, stdout=subprocess.PIPE, env=d).stdout.read()

def launch_opscenter():
    logger.info('Starting a background process to start OpsCenter after a given delay...')
    subprocess.Popen(shlex.split('sudo -u ubuntu python /home/ubuntu/datastax_ami/ds3_after_init.py &'))

def start_services():
    # Wait for system setup changes to settle
    time.sleep(5)

    # Actually start the application
    if conf.get_config("AMI", "Type") == "Community" or conf.get_config("AMI", "Type") == "False":
        logger.info('Starting DataStax Community...')
        logger.exe('sudo service cassandra restart')

    elif conf.get_config("AMI", "Type") == "Enterprise":
        logger.info('Starting DataStax Enterprise...')
        logger.exe('sudo service dse restart')

    # Wait 30 seconds for the Cassandra services to fully boot
    time.sleep(30)

    # Ensure that cassandra doesn't die shortly after first boot
    # I've seen issues with a device not being available... but this is after the full raid
    if not conf.get_config("AMI", "CompletedFirstBoot"):
        start_time = time.time()
        logger.info('Checking for 15 seconds to ensure Cassandra stays up...')
        while time.time() - start_time < 15:
            cassandra_running = False
            if not logger.exe('nodetool info', expectError=True)[1]:
                cassandra_running = True

            if not cassandra_running:
                # Restart the application
                if conf.get_config("AMI", "Type") == "Community" or conf.get_config("AMI", "Type") == "False":
                    logger.info('Restarting DataStax Community...')
                    logger.exe('sudo service cassandra restart')

                elif conf.get_config("AMI", "Type") == "Enterprise":
                    logger.info('Restarting DataStax Enterprise...')
                    logger.exe('sudo service dse restart')
                time.sleep(3)
            time.sleep(1)

def run():
    initial_configurations()
    write_bin_tools()
    restart_tasks()
    if conf.get_config("AMI", "OpsCenterOnly"):
        logger.exe('sudo service opscenterd restart')
    if conf.get_config("AMI", "LeadingSeed"):
        wait_for_seed()
        launch_opscenter()
        start_services()
