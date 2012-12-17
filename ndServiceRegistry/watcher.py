#!/usr/bin/python
#
# Copyright 2012 Nextdoor.com, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Kazoo Zookeeper znode watch object

Copyright 2012 Nextdoor Inc."""

__author__ = 'matt@nextdoor.com (Matt Wise)'

import logging
import threading
import time
import sys
from os.path import split

from ndServiceRegistry import funcs

# For KazooServiceRegistry Class
import kazoo.exceptions

# Our default variables
from version import __version__ as VERSION

TIMEOUT = 30


class Watcher(object):
    """Watches a Zookeeper path for children and data changes.

    This object provides a way to access and monitor all of the data on a
    given Zookeeper node. This includes its own node data, its children, and
    their data. It is not recursive.

    The object always maintains a local cached copy of the current state of
    the supplied path. This state can be accessed at any time by calling
    the get() method. Data will be returned in this format:

        {
            'data': { 'foo': 'bar', 'abc': 123' },
            'stat': ZnodeStat(czxid=116, mzxid=4032, ctime=1355424939217,
                    mtime=1355523495703, version=5, cversion=1912, aversion=0,
                    ephemeralOwner=0, dataLength=9, numChildren=2, pzxid=8388),
            'children': {
                'node1:22': { 'data': 'value' },
                'node2:22': { 'data': 'value2' },
            },
            'path': '/services/foo',
        }
    """

    LOGGING = 'ndServiceRegistry.Watcher'

    def __init__(self, zk, path, callback=None, watch_children=True):
        # Create our logger
        self.log = logging.getLogger('%s.%s' % (self.LOGGING, path))

        # Set our local variables
        self._zk = zk
        self._path = path
        self._watch_children = watch_children

        # Create local caches of the 'data' and the 'children' data
        self._children = {}
        self._data = None
        self._stat = None

        # Array to hold any callback functions we're supposed to notify when
        # anything changes on this path
        self._callbacks = []
        if callback:
            self._callbacks.append(callback)

        # if self._state is False, then even on a data change, our callbacks
        # do not run.
        self._state = True

        # Start up
        self._begin()

    def get(self):
        """Returns local data/children in specific dict format"""
        ret = {}
        ret['stat'] = self._stat
        ret['path'] = self._path
        ret['data'] = self._data
        ret['children'] = self._children
        return ret

    def stop(self):
        """Stops watching the path."""
        # Stop the main run() method
        self._state = False

    def start(self):
        """Starts watching the path."""
        # Stop the main run() method
        self._state = True

    def state(self):
        """Returns self._state"""
        return self._state

    def add_callback(self, callback):
        """Add a callback when watch is updated."""
        for existing_callback in self._callbacks:
            if callback == existing_callback:
                self.log.warning('Callback [%s] already exists. Not '
                                 'triggering again.' % callback)
                return

        self._callbacks.append(callback)
        callback(self.get())

    def _begin(self):
        # First, register a watch on the data for the path supplied.
        self.log.debug('Registering watch on data changes')
        @self._zk.DataWatch(self._path, allow_missing_node=True)
        def _update_root_data(data, stat):
            self.log.debug('Data change detected')

            # Since we set allow_missing_node to True, the 'data' passed back
            # is ALWAYS 'None'. This means that we need to actually go out and
            # explicitly get the data whenever this function is called. As
            # long as 'stat' is not None, we know the node exists so this will
            # succeed.
            if stat:
                self.log.debug('Node is registered.')
                data, self._stat = self._zk.retry(self._zk.get, self._path)
            else:
                # Just a bit of logging
                self.log.debug('Node is not registered.')

            self._data = funcs.decode(data)
            self._stat = stat 

            self.log.debug('Data: %s, Stat: %s' % (self._data, self._stat))
            self._execute_callbacks()

        # Only register a watch on the children if this path exists. If
        # it doesnt, we're assuming that you're watching a specific node
        # that may or may not be registered.
        if self._zk.exists(self._path) and self._watch_children:
            self.log.debug('Registering watch on child changes')
            @self._zk.ChildrenWatch(self._path)
            def _update_child_list(data):
                self.log.debug('New children: %s' % sorted(data))
                children = {}
                for child in data:
                    fullpath = '%s/%s' % (self._path, child)
                    data, stat = self._zk.retry(self._zk.get, fullpath)
                    children[child] = funcs.decode(data)
                self._children = children
                self._execute_callbacks()

    def _execute_callbacks(self):
        """Runs any callbacks that were passed to us for a given path.

        Args:
            path: A string value of the 'path' that has been updated. This
                  triggers the callbacks registered for that path only."""
        self.log.debug('execute_callbacks triggered')

        if not self.state():
            self.log.debug('self.state() is False - not executing callbacks.')
            return

        for callback in self._callbacks:
            self.log.warning('Executing callback %s' % callback)
            callback(self.get())
