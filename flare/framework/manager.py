from multiprocessing import Queue
from threading import Thread
from flare.framework.computation_task import ComputationTask
from flare.common.log import GameLogger
import signal
import time
import sys
import os


class Manager(object):
    def __init__(self, ct_settings, log_settings=dict()):
        """
            Initialize `Manager`. `ct_settings` is used to create
            `ComputationTask`; The parameters in `ct_settings` are for each
            `ComputationTask`.
        """
        ## default settings
        log_settings_ = dict(
            print_interval=100,
            load_model=False,
            model_dir="",
            pass_num=0,
            model_save_interval=10,
            log_file="")
        ## update with the user provided ones
        log_settings_.update(log_settings)
        log_settings = log_settings_

        self.agents = []
        self.logger = GameLogger(
            timeout=1,
            print_interval=log_settings["print_interval"],
            model_save_interval=log_settings["model_save_interval"],
            log_file=log_settings["log_file"])
        self.cts = {}
        self.CDPs = {}
        for name, setting in ct_settings.items():
            setting["model_dir"] = log_settings["model_dir"]
            setting["pass_num"] = log_settings["pass_num"]
            setting["load_model"] = log_settings["load_model"]
            self.cts[name] = ComputationTask(name, **setting)
            self.CDPs[name] = self.cts[name].CDP
            self.logger.model_save_signals.append(self.cts[name]
                                                  .model_save_signal)

    def __signal_handler(self, sig, frame):
        # this is still not good, as we don't get a chance to normally stop
        # the processes.
        print("user signaled ctrl+c")
        for cdp in self.CDPs.values():
            cdp.stop()
        for agent in self.agents:
            agent.running.value = 0
            agent.join()

        self.logger.running.value = False
        self.logger.join()
        sys.exit(0)

    def add_agents(self, agents):
        assert isinstance(agents, list)
        for agent in agents:
            self.add_agent(agent)

    def add_agent(self, agent):
        agent.id = len(self.agents)
        # `Agent` needs to know the state specs to prepare state data
        agent.cts_state_specs = \
            {k: v.get_state_specs()
             for k, v in self.cts.items()}
        self.agents.append(agent)
        for name, cdp in self.CDPs.items():
            agent.add_agent_helper(
                cdp.create_agent_helper(agent.id),
                [s[0] for s in self.cts[name].get_input_specs()],
                [s[0] for s in self.cts[name].get_action_specs()],
                [s[0] for s in self.cts[name].get_state_specs()],
                [s[0] for s in self.cts[name].get_reward_specs()])
            agent.log_q = self.logger.log_q

    def remove_agent(self):
        self.agents[-1].running.value = 0
        self.agents[-1].join()
        self.agents.pop()

    def start(self):
        signal.signal(signal.SIGINT, self.__signal_handler)
        self.logger.start()
        for agent in self.agents:
            agent.start()

        while True:
            # wait for all agents running value==1
            if all([a.running.value for a in self.agents]):
                break

        for cdp in self.CDPs.values():
            cdp.run([a.running for a in self.agents])

        while self.agents:
            self.agents[-1].join()
            self.agents.pop()

        for cdp in self.CDPs.values():
            cdp.stop()

        # Retrieve all the stats from the logger
        self.logger.running.value = False
        self.stats = self.logger.stats_q.get()
        self.logger.join()
