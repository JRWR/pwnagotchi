#!/usr/bin/python3
import os
import argparse
import time
import logging

import yaml

import pwnagotchi
import pwnagotchi.utils as utils
import pwnagotchi.version as version
import pwnagotchi.plugins as plugins

from pwnagotchi.log import SessionParser
from pwnagotchi.agent import Agent
from pwnagotchi.ui.display import Display

parser = argparse.ArgumentParser()

parser.add_argument('-C', '--config', action='store', dest='config', default='/root/pwnagotchi/config.yml',
                    help='Main configuration file.')
parser.add_argument('-U', '--user-config', action='store', dest='user_config', default='/root/custom.yml',
                    help='If this file exists, configuration will be merged and this will override default values.')

parser.add_argument('--manual', dest="do_manual", action="store_true", default=False, help="Manual mode.")
parser.add_argument('--clear', dest="do_clear", action="store_true", default=False,
                    help="Clear the ePaper display and exit.")

parser.add_argument('--debug', dest="debug", action="store_true", default=False,
                    help="Enable debug logs.")

args = parser.parse_args()
config = utils.load_config(args)
utils.setup_logging(args, config)

plugins.load_from_path(plugins.default_path)
if 'plugins' in config['main'] and config['main']['plugins'] is not None:
    plugins.load_from_path(config['main']['plugins'])

plugins.on('loaded')

display = Display(config=config, state={'name': '%s>' % pwnagotchi.name()})
agent = Agent(view=display, config=config)

logging.info("%s@%s (v%s)" % (pwnagotchi.name(), agent._identity, version.version))

for _, plugin in plugins.loaded.items():
    logging.debug("plugin '%s' v%s loaded from %s" % (plugin.__name__, plugin.__version__, plugin.__file__))

if args.do_clear:
    logging.info("clearing the display ...")
    display.clear()

elif args.do_manual:
    logging.info("entering manual mode ...")

    log = SessionParser(config['main']['log'])
    logging.info(
        "the last session lasted %s (%d completed epochs, trained for %d), average reward:%s (min:%s max:%s)" % (
            log.duration_human,
            log.epochs,
            log.train_epochs,
            log.avg_reward,
            log.min_reward,
            log.max_reward))

    while True:
        display.on_manual_mode(log)
        time.sleep(1)

        if Agent.is_connected():
            plugins.on('internet_available', display, config, log)

else:
    logging.info("entering auto mode ...")

    agent.start_ai()
    agent.setup_events()
    agent.set_starting()
    agent.start_monitor_mode()
    agent.start_event_polling()

    # print initial stats
    agent.next_epoch()

    agent.set_ready()

    while True:
        try:
            # recon on all channels
            agent.recon()
            # get nearby access points grouped by channel
            channels = agent.get_access_points_by_channel()
            # check for free channels to use
            agent.check_channels(channels)
            # for each channel
            for ch, aps in channels:
                agent.set_channel(ch)

                if not agent.is_stale() and agent.any_activity():
                    logging.info("%d access points on channel %d" % (len(aps), ch))

                # for each ap on this channel
                for ap in aps:
                    # send an association frame in order to get for a PMKID
                    agent.associate(ap)
                    # deauth all client stations in order to get a full handshake
                    for sta in ap['clients']:
                        agent.deauth(ap, sta)

            # An interesting effect of this:
            #
            # From Pwnagotchi's perspective, the more new access points
            # and / or client stations nearby, the longer one epoch of
            # its relative time will take ... basically, in Pwnagotchi's universe,
            # WiFi electromagnetic fields affect time like gravitational fields
            # affect ours ... neat ^_^
            agent.next_epoch()
        except Exception as e:
            logging.exception("main loop exception")
