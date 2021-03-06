#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Apr  2 20:35:23 2020

@author: mostafh
"""
import logging
import pandas as pd
import numpy as np
import os.path
from psychsim.action import ActionSet
from psychsim.pwl import stateKey, isStateKey, state2feature
from psychsim.world import WORLD

ACTION = 0
SET_FLG = 1
SEARCH = 3

MAX_MISSION_TIMER = 10 * 60  # max num seconds in game's timer


class ProcessCSV(object):

    def __init__(self, filename, maxDist=5, logger=logging):
        self.maxDist = maxDist
        self.filename = filename
        self.actions = []
        if os.path.splitext(filename)[1] == '.xlsx':
            self.data = pd.read_excel(filename)
        elif os.path.splitext(filename)[1] == '.csv':
            self.data = pd.read_csv(filename)
        else:
            raise NameError('Unable to process data file with "{}" extension'.format(os.path.splitext(filename)[1]))
        self.maxVicsInLoc = self.data['num_victims'].max()

        self.cols = [
            'Room_in',
            'num_victims',
            'isAVicInFOV',
            'event_triage_victim_id',
            'triage_in_progress',
            'triage_result',
            'mission_timer']

        self.logger = logger

        for iv in range(self.maxVicsInLoc):
            self.cols = self.cols + [
                'victim_' + str(iv) + '_id',
                'victim_' + str(iv) + '_color',
                'victim_' + str(iv) + '_in_FOV']

        # Remove rows w/o locations
        self.logger.info('Number of rows %d' % (len(self.data)))
        self.data.dropna(axis=0, subset=['Room_in'], inplace=True)
        self.data = self.data.loc[self.data['Room_in'] != 'None', :]
        self.logger.info('Number of rows after empty room removal %d' % (len(self.data)))

        # Remove in_progress rows that were never back-filled
        self.data = self.data.loc[self.data['triage_result'] != 'IN_PROGRESS', :]
        self.logger.info('Number of rows after triage in progress removal %d' % (len(self.data)))

        # Remove triage_in_progress rows where victim being triaged different from victim in CH
        triageOn = self.data['triage_in_progress'] == True
        sameVic = self.data['event_triage_victim_id'] == self.data['victim_in_crosshair_id']
        self.data = self.data.loc[~triageOn | sameVic, :]
        self.logger.info('Number of rows after inconsistent triage vic and CH removal %d' % (len(self.data)))

        # Rooms with numeric names: Prepend 'R'
        mask = self.data['Room_in'].str.startswith('2')
        newRoom = 'R' + self.data['Room_in']
        self.data.loc[mask, 'Room_in'] = newRoom.loc[mask]
        self.data['Room_in'] = self.data['Room_in'].astype(str)

        # Remove 'd' or 'x' at the end of room names
        rooms = [str(loc) for loc in self.data['Room_in'].unique()]
        newRooms = {r: r for r in rooms if not (r.endswith('x') or r.endswith('d'))}
        newRooms.update({r: r[:-1] for r in rooms if r.endswith('x') or r.endswith('d')})
        self.data['Room_in'].replace(newRooms, inplace=True)

        ## Create flag for whether any victim is in FOV
        self.data['isAVicInFOV'] = self.data['victim_0_in_FOV']
        for iv in range(1, self.maxVicsInLoc):
            self.data['isAVicInFOV'] = self.data['isAVicInFOV'] | self.data['victim_' + str(iv) + '_in_FOV']

        # Collect names of locations
        self.locations = [str(loc) for loc in self.data['Room_in'].unique()]

        #        fstr1 = '%Y-%m-%dT%H:%M:%S.%fZ'
        #        fstr2 = '%Y-%m-%dT%H:%M:%SZ'
        #            self.data['dtime'] = pd.to_datetime(self.data['@timestamp'], format=fstr1, exact=False)
        self.data['dtime'] = pd.to_datetime(self.data['@timestamp'], infer_datetime_format=True, exact=False)

        self.chkCHAndFOV()

    def chkCHAndFOV(self):
        ## Warn if multiple vics in FOV
        numInFov = self.data.loc[:, 'victim_0_in_FOV']
        for iv in range(1, self.maxVicsInLoc):
            numInFov = numInFov + self.data['victim_' + str(iv) + '_in_FOV'].astype(int)
        numManyFOV = np.count_nonzero(numInFov > 1)
        if numManyFOV > 0:
            self.logger.warning('%d rows with multiple victims in FOV' % (numManyFOV))

        ## Can't have vic in CH but none in FOV
        chNotFOV = self.data.loc[self.data['triage_in_progress'] & \
                                 (self.data['victim_in_crosshair_id'] != 'None') & \
                                 (self.data['isAVicInFOV'] == False)]
        if len(chNotFOV) > 0:
            self.logger.warn('Triage and victim in CH but none in FOV ' + str(len(chNotFOV)))

        ## If multiple in FOV, set FOV flag of all but the CH victim to False
        manyFOV = numInFov[numInFov > 1]
        for idx in manyFOV.index:
            vicInCH = self.data.loc[idx, 'victim_in_crosshair_id']
            for vi in range(self.maxVicsInLoc):
                thisID = self.data.loc[idx, 'victim_' + str(vi) + '_id']
                if thisID == 'None':
                    break
                self.data.loc[idx, 'victim_' + str(vi) + '_in_FOV'] = (vicInCH == thisID)

    def parseFOV(self, row, newRoom, prevRow, victims, searchActs):
        ''' For each victim, if in distance range, add approach action        
        '''
        someoneInFOV = row['isAVicInFOV']
        for vi in range(self.maxVicsInLoc):
            color = row['victim_' + str(vi) + '_color']
            inFov = row['victim_' + str(vi) + '_in_FOV']
            if not prevRow.empty:
                prevFOV = prevRow['victim_' + str(vi) + '_in_FOV']

            if newRoom or (not prevFOV):
                if inFov:  # this dude just got into my FOV because of a search action
                    searchActs.append([victims.getSearchAction(self.human), color])
                    self.logger.debug('Searched and found %s' % (color))
            else:  # same room and previously in FOV
                # Either remain in FOV ==> noop
                # Or search action found: a) another victim ==> search action injected in another iteration of vi
                # or b) none  ==> set approached to none outside the loop
                pass

        if prevRow.empty:
            prevSomeone = False
        else:
            prevSomeone = prevRow['isAVicInFOV']
        if prevSomeone and (not someoneInFOV) and (not newRoom):
            searchActs.append([victims.getSearchAction(self.human), 'none'])
            self.logger.debug('Searched and found none')

    def getFOVColor(self, row):
        for vi in range(self.maxVicsInLoc):
            if row['victim_' + str(vi) + '_in_FOV']:
                return row['victim_' + str(vi) + '_color']

    def getDurationIfTriaging(self, row, originalDuration):
        # Quantize duration to 5, 8 or 15
        if not row['triage_in_progress']:
            return originalDuration

        fovColor = self.getFOVColor(row)
        if originalDuration <= 7:
            duration = 5
        elif (originalDuration > 7) and (originalDuration < 15):
            if fovColor == 'Green':
                duration = 8
            else:
                duration = 5
        elif originalDuration >= 15:
            if fovColor == 'Green':
                duration = 8
            else:
                duration = 15
        return duration

    def getActionsAndEvents(self, victims, world_map, maxEvents=-1):
        """
        Gets actions and events from this parser's log for the given agent.
        :param Agent human: the PsychSim agent for which we are going to parse data.
        :param Victims victims: the distribution of victims over the world.
        :param WorldMap world_map: the world map with all locations.
        :param bool printTrace: whether to print the collected trace.
        :param int maxEvents: the maximum number of events to be parsed.
        :return:
        """

        ## Assume we're only interested in the player appearing on the first row
        self.human = self.player_name()
        self.pData = self.data.loc[self.data['player_ID'] == self.human]

        locs = sorted([l for l in self.data['Room_in'].unique() if not l in world_map.all_locations])
        if len(locs) > 0:
            self.logger.warning('Locations in player data but not map %s' % (','.join(locs)))

        ## Sort by time
        self.pData = self.pData.loc[:, ['dtime'] + self.cols].sort_values('dtime', axis=0)

        self.pData.to_csv('debug.csv')

        ## Drop consecutive duplicate entries (ignoring the timestamp)
        self.pData = self.pData.loc[(self.pData[self.cols].shift() != self.pData[self.cols]).any(axis=1)]
        self.logger.info('Dropped duplicates. Down to %d' % (len(self.pData)))

        self.pData['duration'] = np.ceil(-self.pData['dtime'].diff(periods=-1) / np.timedelta64(1, 's'))
        self.pData['duration'].values[-1] = 0

        prev = pd.Series()
        lastLoc = None
        attemptID = 0
        start_stamp = None
        for ir, row in self.pData.iterrows():
            if (maxEvents > 0) and (len(self.actions) > maxEvents):
                break
            triageActs = []
            events = []
            moveActs = []
            searchActs = []
            stamp = row['dtime']
            mission_timer = row['mission_timer']
            duration = row['duration']
            duration = self.getDurationIfTriaging(row, duration)

            # Entered a new room.
            if row['Room_in'] != lastLoc:
                if lastLoc == None:
                    # First elements in actions is the intial location
                    moveActs = [row['Room_in']]
                else:
                    # Add a move action
                    mv = world_map.getMoveAction(self.human, lastLoc, row['Room_in'])
                    if mv == []:
                        self.logger.warning('unreachable %s %s %s' % (lastLoc, row['Room_in'], row['dtime']))
                        #                        ## Transport player to new location by force
                        #                        events.append(['loc', row['Room_in']])
                        continue
                    for m in mv:
                        moveActs.append(m)

                lastLoc = row['Room_in']
                self.logger.debug('moved to %s %s' % (lastLoc, stamp))

                self.parseFOV(row, True, prev, victims, searchActs)

                # Is a TIP in this new room? 
                if row['triage_in_progress']:
                    ## event_triage_victim_id
                    fovColor = self.getFOVColor(row)
                    triageAct = victims.getTriageAction(self.human, fovColor)
                    triageActs.append([triageAct, duration])
                    self.logger.debug('triage started in new room')

            # same room. Compare flag values to know what changed!
            else:
                self.parseFOV(row, False, prev, victims, searchActs)

                # If TIP changed
                tip = 'triage_in_progress'
                tstatus = 'triage_result'
                if (row[tip] != prev[tip]) or (row[tstatus] != prev[tstatus]):
                    if row[tip]:
                        fovColor = self.getFOVColor(row)
                        triageAct = victims.getTriageAction(self.human, fovColor)
                        triageActs.append([triageAct, duration])
                        self.logger.debug('triage started')
                    if prev[tip]:
                        attemptID = attemptID + 1

            ## Inject move action(s), then events, then crosshair/approach actions
            ## If we have move act(s), the first one take all duration and the rest 0
            for i, mact in enumerate(moveActs):
                dur = 0
                if i == 0:
                    dur = duration
                    duration = 0
                self.actions.append([ACTION, [mact], stamp, dur, attemptID, mission_timer])
            for i, sact in enumerate(searchActs):
                dur = 0
                if i == 0:
                    dur = duration
                    duration = 0
                ## Enforce the value in the data on actions that don't otherwise affect approached victim                
                self.actions.append([SEARCH, sact, stamp, dur, attemptID, mission_timer])
            # acts = triage 
            for i, act in enumerate(triageActs):
                ## Enforce the value in the data on actions that don't otherwise affect approached victim                
                self.actions.append([ACTION, act, stamp, duration, attemptID, mission_timer])
                duration = 0

            for ev in events:
                dur = 0
                if i == 0:
                    dur = duration
                    duration = 0
                self.actions.append([SET_FLG, ev, stamp, dur, attemptID, mission_timer])

            prev = row

    def pre_step(self, world):
        pass

    def post_step(self, world, act):
        pass

    def runTimeless(self, world, start, end, ffwdTo=0, prune_threshold=None, permissive=False):
        """
        Run actions and flag resetting events in the order they're given. No notion of timestamps
        """
        self.logger.debug(self.actions[start])
        for t in range(start, end):
            actOrEvFlag, actEv, stamp, duration, attempt, mission_timer = self.actions[t]

            if t == 0:
                if actOrEvFlag == SET_FLG:
                    varName = actEv[0]
                    varValue = actEv[1]
                    world.setState(self.human, varName, varValue)
                    world.agents[self.human].setBelief(stateKey(self.human, varName), varValue)
                else:
                    # This first action can be an actual action or an initial location
                    if type(actEv) == ActionSet:
                        world.step(actEv)
                    else:
                        world.setState(self.human, 'loc', actEv[0])
                        world.agents[self.human].setBelief(stateKey(self.human, 'loc'), actEv[0])
                        world.setState(self.human, 'locvisits_' + actEv[0], 1)
                        world.agents[self.human].setBelief(stateKey(self.human, 'locvisits_' + actEv[0]), 1)
                continue

            # manually sync the time feature with the game's time (invert timer)
            world.setFeature(stateKey(WORLD, 'seconds'), MAX_MISSION_TIMER - mission_timer, recurse=True)

            self.pre_step(world)
            act = None
            self.logger.info('%d) Running: %s' % (t, ','.join(map(str, actEv))))
            if t >= ffwdTo:
                input('press any key.. ')
            if actOrEvFlag == ACTION:
                act = actEv[0]
                legal_choices = world.agents[self.human].getLegalActions()
                if act not in legal_choices:
                    raise ValueError('Illegal action ({}) at time {}. Legal choices: {}'.format(
                        act, t, ', '.join(sorted(map(str, legal_choices)))))
                selDict = {k: world.value2float(k, 'none') for k in world.state.keys() if
                           isStateKey(k) and state2feature(k)[:6] == 'sensor'}
                if len(actEv) > 1:
                    dur = actEv[1]
                    # This is a triage action with an associated duration
                    clock = stateKey(WORLD, 'seconds')
                    curTime = world.getState(WORLD, 'seconds', unique=True)
                    newTime = curTime + dur
                    selDict[clock] = newTime
                    self.logger.debug('Time now %d triage until %d' % (curTime, newTime))
                self.logger.info('Action: {}'.format(','.join(map(str, sorted(selDict.keys())))))
                world.step(act, select=selDict, threshold=prune_threshold)
                world.modelGC()

            elif actOrEvFlag == SET_FLG:
                [var, val] = actEv
                key = stateKey(self.human, var)
                world.state[key] = world.value2float(key, val)
                for model in world.getModel(self.human).domain():
                    if val not in world.getFeature(key, world.agents[self.human].models[model]['beliefs']).domain():
                        raise ValueError('Unbelievable data point at time %s: %s=%s' % (stamp, var, val))
                    world.agents[self.human].models[model]['beliefs'][key] = world.value2float(key, val)
                self.logger.info('Set: {}'.format(key))

            elif actOrEvFlag == SEARCH:
                act, color = actEv[0], actEv[1]
                selDict = {k: world.value2float(k, 'none') for k in world.state.keys() if
                           isStateKey(k) and state2feature(k)[:6] == 'sensor'}
                selDict[stateKey(self.human, 'vicInFOV')] = world.value2float(stateKey(self.human, 'vicInFOV'), color)
                loc = world.getState(self.human, 'loc', unique=True)
                if permissive and color != 'none' and world.getState(WORLD, 'ctr_{}_{}'.format(loc, color),
                                                                     unique=True) == 0:
                    # Observed a victim who should not be here
                    self.logger.warning('In {}, a nonexistent {} victim entered the FOV'.format(loc, color))
                    continue
                else:
                    self.logger.info('Search: {}'.format(','.join(map(str, sorted(selDict.keys())))))
                    world.step(act, select=selDict, threshold=prune_threshold)
                    world.modelGC()

            self.summarizeState(world)
            self.post_step(world, None if act is None else world.getAction(self.human))

    def summarizeState(self, world):
        self.logger.info('_____________________________________')
        loc = world.getState(self.human, 'loc', unique=True)
        time = world.getState(WORLD, 'seconds', unique=True)
        self.logger.info('Time: %d (%s)' % (time, world.getState(WORLD, 'phase', unique=True)))

        self.logger.info('Player location: %s' % (loc))
        clrs = ['Green', 'Gold', 'Red', 'White']
        for clr in clrs:
            self.logger.debug('%s count: %s' % (clr, world.getState(WORLD, 'ctr_' + loc + '_' + clr, unique=True)))
        self.logger.info('FOV: %s' % (world.getState(self.human, 'vicInFOV', unique=True)))
        self.logger.info('Visits: %d' % (world.getState(self.human, 'locvisits_' + loc, unique=True)))
        self.logger.info('JustSavedGr: %s' % (world.getState(self.human, 'numsaved_Green', unique=True)))
        self.logger.info('JustSavedGd: %s' % (world.getState(self.human, 'numsaved_Gold', unique=True)))

    def player_name(self):
        """
        :return: the name of the human player in this log file
        :rtype: str
        """
        return self.data['player_ID'].iloc[0]


def printAEs(aes, logger=logging):
    for ae in aes:
        logger.info('%s %s' % (ae[2], ae[1]))
