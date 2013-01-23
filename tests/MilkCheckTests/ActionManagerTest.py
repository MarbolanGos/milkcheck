# Copyright CEA (2011)
# Contributor: TATIBOUET Jeremie <tatibouetj@ocre.cea.fr>

"""
This modules defines the tests cases targeting the class ActionManager
"""

# Classes
import socket
from unittest import TestCase
from MilkCheck.Engine.Action import Action
from MilkCheck.Engine.Service import Service
from MilkCheck.ActionManager import ActionManager, action_manager_self

HOSTNAME = socket.gethostname().split('.')[0]

class ActionManagerTest(TestCase):
    """Test cases for action_manager_self"""

    def setUp(self):
        ActionManager._instance = None

    def tearDown(self):
        ActionManager._instance = None

    def assert_near(self, target, delta, value):
        """Like self.assertTrue(target - delta < value < target + delta)"""
        low = target - delta
        high = target + delta
        self.assertTrue(low <= value <= high,
                        "%.2f is not [%f and %f]" % (value, low, high))

    def test_instanciation(self):
        """Test singleton handling of action_manager_self"""
        task_manager = action_manager_self()
        other_task_manager = action_manager_self()
        self.assertTrue(task_manager is other_task_manager)

    def test_add_task(self):
        """Test the behaviour of the add_task method"""
        task_manager = action_manager_self()
        task1 = Action('start')
        task1.fanout = 60
        task2 = Action('stop')
        task2.fanout = 12
        task3 = Action('status')
        task3.fanout = 50
        task_manager.add_task(task1)
        task_manager.add_task(task2)
        task_manager.add_task(task3)
        task_manager.add_task(task3)
        self.assertEqual(task_manager.fanout, 12)
        task4 = Action('check')
        task4.fanout = 3
        task_manager.add_task(task4)
        self.assertEqual(task_manager.fanout, 3)
        self.assertEqual(task_manager.tasks_count, 4)
        self.assertEqual(task_manager.tasks_done_count, 4)

    def test_add_task_weird_values(self):
        """Test the method add task with task without fanout"""
        task_manager = action_manager_self()
        task1 = Action('start')
        task1.fanout = 60
        task2 = Action('stop')
        task3 = Action('status')
        task3.fanout = 50
        task_manager.add_task(task1)
        task_manager.add_task(task2)
        task_manager.add_task(task3)
        self.assertEqual(task_manager.fanout, 50)
        self.assertEqual(task_manager.tasks_count, 3)

    def test_remove_task(self):
        """Test the behaviour of the remove_task method"""
        task_manager = action_manager_self()
        task1 = Action('start')
        task1.fanout = 260
        task2 = Action('stop')
        task2.fanout = 85
        task3 = Action('status')
        task3.fanout = 85
        task4 = Action('check')
        task4.fanout = 148
        task_manager.add_task(task1)
        task_manager.add_task(task2)
        task_manager.add_task(task3)
        task_manager.add_task(task4)
        task_manager.remove_task(task2)
        self.assertEqual(task_manager.fanout, 85)
        task_manager.remove_task(task3)
        self.assertEqual(task_manager.fanout, 148)
        task_manager.remove_task(task4)
        self.assertEqual(task_manager.fanout, 260)
        task_manager.remove_task(task1)
        self.assertFalse(task_manager.fanout)
        self.assertEqual(task_manager.tasks_count, 0)
        self.assertEqual(task_manager.tasks_done_count, 4)

    def test__is_running_task(self):
        """Test the behaviour of the method _is_running_task"""
        task_manager = action_manager_self()
        task1 = Action('start')
        task1.fanout = 260
        task2 = Action('stop')
        task2.fanout = 85
        task3 = Action('status')
        task3.fanout = 148
        task4 = Action('check')
        task_manager.add_task(task1)
        task_manager.add_task(task3)
        task_manager.add_task(task4)
        self.assertTrue(task_manager._is_running_task(task3))
        self.assertTrue(task_manager._is_running_task(task4))
        self.assertRaises(AssertionError, task_manager._is_running_task, None)
        self.assertFalse(task_manager._is_running_task(task2))

    def test_set_of_running_task(self):
        """
        Test return a sets of running tasks from the property running_tasks
        """
        task_manager = action_manager_self()
        task1 = Action('start')
        task1.fanout = 260
        task2 = Action('stop')
        task2.fanout = 85
        task3 = Action('status')
        task3.fanout = 148
        task_manager.add_task(task1)
        task_manager.add_task(task2)
        task_manager.add_task(task3)
        self.assertTrue(task_manager.running_tasks)
        self.assertEqual(len(task_manager.running_tasks), 3)

    def test_perform_action(self):
        """test perform an action without any delay"""
        action = Action('start', HOSTNAME, '/bin/true')
        ser = Service('TEST')
        ser.add_action(action)
        ser.run('start')
        task_manager = action_manager_self()
        self.assertEqual(task_manager.tasks_done_count, 1)
        self.assertTrue(action.duration < 0.5,
                        "Too long: %.2f > 0.5" % action.duration)

    def test_perform_action_bad_service(self):
        '''test perform action with a simulate service hooked to the action'''
        action = Action(name='start', command=':')
        ser = Service('TEST')
        ser.simulate = True
        ser.add_action(action)
        ser.run('start')
        task_manager = action_manager_self()
        self.assertEqual(task_manager.tasks_done_count, 0)

    def test_perform_delayed_action_bad_service(self):
        '''
        test perform delayed action with a simulate service hooked to
        the action
        '''
        action = Action(name='start', command=':', timeout=0.01)
        ser = Service('TEST')
        ser.simulate = True
        ser.add_action(action)
        ser.run('start')
        task_manager = action_manager_self()
        self.assertEqual(task_manager.tasks_done_count, 0)

    def test_perform_delayed_action(self):
        """test perform an action with a delay"""
        action = Action('start', HOSTNAME, 'sleep 0.5')
        ser = Service('TEST')
        ser.add_action(action)
        ser.run('start')
        task_manager = action_manager_self()
        ActionManager._instance = None
        self.assertEqual(task_manager.tasks_done_count, 1)
        # SSH could length up to 0.4 sec.
        # So max is 0.5 + 0.4 = 0.9, min is 0.5
        # Average is: 0.7 +/- 0.2
        self.assert_near(0.7, 0.2, action.duration)
