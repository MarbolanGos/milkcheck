# Copyright CEA (2011) 
# Contributor: TATIBOUET Jeremie <tatibouetj@ocre.cea.fr>

"""
This module contains the Action class definition. It also contains the
definition of a basic event handler and the ActionEventHandler.
"""
# Classes
from re import sub, findall
from datetime import datetime
from ClusterShell.Task import task_self
from ClusterShell.Event import EventHandler
from MilkCheck.Engine.BaseEntity import BaseEntity
from MilkCheck.Callback import call_back_self

# Exceptions
from MilkCheck.Engine.BaseEntity import MilkCheckEngineError

# Symbols
from MilkCheck.Engine.BaseEntity import DONE, TIMED_OUT, TOO_MANY_ERRORS
from MilkCheck.Engine.BaseEntity import WAITING_STATUS
from MilkCheck.Engine.BaseEntity import NO_STATUS, ERROR
from MilkCheck.Callback import EV_COMPLETE, EV_DELAYED, EV_STATUS_CHANGED
from MilkCheck.Callback import EV_STARTED, EV_TRIGGER_DEP

class UndefinedVariableError(MilkCheckEngineError):
    '''
    This error is raised each time that you make reference to a None existing
    variable located in a command
    '''
    def __init__(self, varname, cmd):
        msg = "Variable [%s] undefined in [%s]" % (varname, cmd)
        MilkCheckEngineError.__init__(self, msg)

class NodeInfo(object):
    '''This class represent the result of command executed on cluster's node'''
    def __init__(self, node, command, nbuffer=None, rcode=None):
        # node used
        self.node = node
        # command performed
        self.command = command
        # node buffer
        self.node_buffer = nbuffer
        # exit code of the command
        self.exit_code = rcode

    @classmethod
    def from_worker(cls, worker):
        '''Build a NodeInfo object from a worker'''
        assert worker, 'worker cannot be None'
        (node, nbuffer) = worker.last_read()
        (node, exit_code) = worker.last_retcode()
        return cls(node, worker.command, nbuffer, exit_code)

    def __repr__(self):
        '''Return a string serializing object's content'''
        return '[%s]:%s:%s' % (self.node, self.command, self.exit_code)

class MilkCheckEventHandler(EventHandler):
    '''
    The basic event handler for MilkCheck derives the class provided
    by ClusterShell to handle events generated by the master task. It contains
    an action as attribute. This action is the element processed through the
    events raised. 
    '''
    
    def __init__(self, action):
        EventHandler.__init__(self)
        assert action, "should not be be None"
        # Current action hooked to the handler
        self._action = action

    def ev_hup(self, worker):
        '''An event hup is raised when a connection to a node is done'''
        call_back_self().notify(NodeInfo.from_worker(worker), EV_COMPLETE)
        
    def ev_timer(self, timer):
        '''
        A timer event is raised when an action was delayed. Now the timer is
        done so we can really execute the action. This method is also used
        to handle action with a service which is specified as ghost. That means
        it does nothing
        '''
        if self._action.service.simulate:
            self._action.service.update_status(
                self._action.service.eval_deps_status())
        else:
            self._action.schedule(allow_delay=False)
       
        
class ActionEventHandler(MilkCheckEventHandler):
    '''
    Inherit from our basic handler and specify others event raised to
    process an action.
    '''
    
    def ev_close(self, worker):
        '''
        This event is raised by the master task as soon as an action is
        done. It specifies the how the action will be computed.
        '''
        
        # Assign time duration to the current action
        self._action.stop_time = datetime.now()
        
        # Callback the interface
        #call_back_self().notify(self._action, EV_COMPLETE)

        # Remove the current action from the running task, this will trigger
        # a redefinition of the current fanout
        action_manager_self().remove_task(self._action)
        
        # Get back the worker from ClusterShell
        self._action.worker = worker
        
        # Checkout actions issues
        error = self._action.has_too_many_errors()
        timed_out = self._action.has_timed_out()
        
        # Classic Action was failed
        if (error or timed_out) and self._action.retry > 0:
            self._action.retry -= 1
            self._action.schedule()

        # failed on too_many_errors
        elif error:
            self._action.update_status(TOO_MANY_ERRORS)
        elif timed_out:
            self._action.update_status(TIMED_OUT)
        else:
            self._action.update_status(DONE)
                
class Action(BaseEntity):
    '''
    This class models an action. An action is generally hooked to a service
    and contains the code and parameters to execute commands over one or several
    nodes of a cluster. An action might have dependencies with other actions.
    '''
    
    def __init__(self, name, target=None, command=None, timeout=0, delay=0):
        BaseEntity.__init__(self, name=name, target=target)
        
        # Action's timeout in seconds/milliseconds
        self.timeout = timeout
        
        # Action's delay in seconds
        self.delay = delay
        
        # Number of action's retry
        self._retry = 0
        self._retry_backup = -1
        
        # Command lines that we would like to run 
        self.command = command
        
        # Results and retcodes
        self.worker = None
        
        # Parent service of this action
        self.service = None
        
        # Allow us to determine time used by an action within the master task
        self.start_time = None
        self.stop_time = None

    def reset(self):
        '''
        Reset values of attributes in order to used the action multiple time.
        '''
        BaseEntity.reset(self)
        self.start_time = None
        self.stop_time = None
        self.worker = None
        self._retry = self._retry_backup

    def run(self):
        '''Prepare the current action and set up the master task'''
        self.prepare()
        task_self().resume()

    def prepare(self):
        '''
        Prepare is a recursive method allowing the current action to prepare
        actions which are in dependency with her first. An action can only
        be prepared whether the dependencies are not currently running and if
        the current action has not already a status.
        '''
        deps_status = self.eval_deps_status()
        # NO_STATUS and not any dep in progress for the current action
        if self.status is NO_STATUS and deps_status is not WAITING_STATUS:
            #print "[%s] is working" % self.name
            if deps_status is ERROR or not self.parents:
                self.update_status(WAITING_STATUS)
                self.schedule()
            elif deps_status is DONE:
                # No need to do the action so just make it DONE
                self.update_status(DONE)
            else:
                # Look for uncompleted dependencies
                deps = self.search_deps([NO_STATUS])
                # For each existing deps just prepare it
                for dep in deps:
                    dep.target.prepare()
            #print "[%s] prepare end" % self.name
                    
    def update_status(self, status):
        '''
        This method update the current status of an action. Whether the
        a status meaning that the action is done is specified, the current
        action triggers her direct dependencies.
        '''
        assert status in (NO_STATUS, WAITING_STATUS, DONE, \
        TOO_MANY_ERRORS, TIMED_OUT),'Bad action status'
        self.status = status
        call_back_self().notify(self, EV_STATUS_CHANGED)
        if status not in (NO_STATUS, WAITING_STATUS):
            # Callback the interface
            call_back_self().notify(self, EV_COMPLETE)
            if self.children:
                for dep in self.children.values():
                    if dep.target.is_ready():
                        call_back_self().notify((self, dep.target), \
                            EV_TRIGGER_DEP)
                        dep.target.prepare()
            else:
                self.service.update_status(self.status)
        
    def has_timed_out(self):
        '''Return whether this action has timed out.'''
        return self.worker and self.worker.did_timeout()
        
    def has_too_many_errors(self):
        '''
        Return true if the amount of error in the worker is greater than
        the limit authorized by the action.
        '''
        too_many_errors = False
        error_count = 0
        if self.worker:
            for retcode, nds in self.worker.iter_retcodes():
                if retcode != 0:
                    error_count += len(nds)
                    if error_count > self.errors:
                        too_many_errors = True
        return too_many_errors
                    
    def set_retry(self, retry):
        '''
        Retry is a property which will be modified during the action life
        cycle. Assigning this property means that the current action has a delay
        greater than 0
        '''
        assert self.delay > 0 , 'No way to specify retry without a delay'
        assert retry >= 0, 'No way to specify a negative retry'
        self._retry = retry
        if self._retry_backup == -1:
            self._retry_backup = retry
        
    def get_retry(self):
        '''Access the property retry in read only'''
        return self._retry
    
    retry = property(fget=get_retry, fset=set_retry) 

    @property
    def duration(self):
        '''
        Task duration in seconds (10^-6) is readable as soon as the task is done
        otherwise it returns None.
        '''
        if not self.start_time or not self.stop_time:
            return None
        else:
            delta = self.stop_time - self.start_time
            return  delta.seconds + (delta.microseconds/1000000.0)

    
    def schedule(self, allow_delay=True):
        '''
        Schedule the current action within the master task. The current action
        could be delayed or fired right now depending of it properties.
        '''
        if not self.start_time:
            self.start_time = datetime.now()
            
        if self.delay > 0 and allow_delay:
            # Action will be started as soon as the timer is done
            call_back_self().notify(self, EV_DELAYED)
            action_manager_self().perform_delayed_action(self)
        else:
            # Fire this action
            call_back_self().notify(self, EV_STARTED)
            action_manager_self().perform_action(self)

    def resolved_command(self):
        '''Return a command with variable's name replaced by values'''
        final_cmd = self.command
        symbols = {}
        for symbol in findall('\${1}[\w]+', self.command):
            varname = symbol.lstrip('$')
            # Look for an attribute matching the symbol in this action
            if hasattr(self, varname.lower()):
                final_cmd = sub(
                    '\%s' % symbol, getattr(self, varname.lower()), final_cmd)
            # Look for a variable matching the symbol in the action 
            elif varname in self.variables:
                final_cmd = sub(
                    '\%s' % symbol, self.variables[varname], final_cmd)
            # Look for an attribute matching the symbol at the service level
            elif hasattr(self.service, varname.lower()):
                final_cmd = sub(
                    '\%s' % symbol,
                        getattr(self.service, varname.lower()), final_cmd)
            # Look for a variable matching the symbol in the service level
            elif self.service and varname in self.service.variables:
                final_cmd = sub(
                    '\%s' % symbol, self.service.variables[varname], final_cmd)
            # Look for an attribute matching the symbol in the manager
            elif hasattr(service_manager_self(), varname.lower()):
                final_cmd = sub(
                    '\%s' % symbol,
                        getattr(
                            service_manager_self(), varname.lower()), final_cmd)
            # Look for a variable matching the symbol at the manager level
            elif varname in service_manager_self().variables:
                final_cmd = sub(
                    '\%s' % symbol, service_manager_self().variables[varname],
                        final_cmd)
            else:
                raise UndefinedVariableError(varname, self.command)
        return final_cmd

from MilkCheck.ActionManager import action_manager_self
from MilkCheck.ServiceManager import service_manager_self