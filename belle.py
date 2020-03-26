# -*- coding: utf-8 -*-
"""
Created on Wed Feb 19 14:35:40 2020

@author: mostafh
"""
from psychsim.world import World
from psychsim.pwl import stateKey, Distribution, actionKey
from locations import Locations
from victims import Victims

Victims.FULL_OBS = False

world = World()
triageAgent = world.addAgent('TriageAg1')
agent = world.addAgent('ATOMIC')

################# Victims and triage actions
## One entry per victim
VICTIMS_LOCS = [2]
VICTIM_TYPES = [0]
Victims.world = world
Victims.makeVictims(VICTIMS_LOCS, VICTIM_TYPES, [triageAgent.name])
Victims.makeTriageAction(triageAgent)

## Create triage agent's observation variables related to victims
if not Victims.FULL_OBS:
    Victims.makeVictimObservationVars(triageAgent)

################# Locations and Move actions
Locations.world = world
Locations.makeMap([(0,1), (1,2)])
Locations.makePlayerLocation(triageAgent, 0)

## These must come before setting triager's beliefs
world.setOrder([{triageAgent.name}])
triageAgent.omega = {actionKey(triageAgent.name)}

## Set uncertain beliefs
if not Victims.FULL_OBS:
    triageAgent.omega = triageAgent.omega.union({stateKey(triageAgent.name, obs) for obs in \
                                                 ['obs_victim_status', 'obs_victim_reward', 'obs_victim_danger']})
    Victims.beliefAboutVictims(triageAgent)

          
world.printBeliefs(triageAgent.name)

Locations.move(triageAgent, 1)
print('======= After moving')

world.printBeliefs(triageAgent.name)

#belief = next(iter(triageAgent.getBelief().values()))
#print(world.float2value(triageLoc,belief[triageLoc]))

#
#
#
#''' The true model of triageAgent has incorrect beliefs about its location
#    It also has info about victims, which shouldn't be there
#'''
#trueTriageModel = next(iter(triageAgent.models.keys())) 
#print('triageAgent.models[trueTriageModel]')
#print('triage loc', triageAgent.models[trueTriageModel]['beliefs'][triageLoc])
#print('victim0 loc', triageAgent.models[trueTriageModel]['beliefs']['victim0\'s loc'])