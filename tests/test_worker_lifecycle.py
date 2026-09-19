import unittest
import threading
import time
from laserforge.core.worker_lifecycle import WorkerLifecycleManager, get_lifecycle_manager, ManagedWorker

class TestWorkerLifecycle(unittest.TestCase):
    def setUp(self):
        self.manager = get_lifecycle_manager()
        # Ensure clean state
        with self.manager._lock:
            self.manager._workers.clear()

    def test_singleton(self):
        manager1 = WorkerLifecycleManager()
        manager2 = WorkerLifecycleManager()
        self.assertIs(manager1, manager2)
        self.assertIs(manager1, self.manager)

    def test_register_and_list_running(self):
        def dummy_worker():
            time.sleep(0.5)

        thread = threading.Thread(target=dummy_worker)
        thread.start()
        
        self.manager.register("dummy_worker", thread)
        running = self.manager.list_running()
        self.assertIn("dummy_worker", running)

        thread.join()
        running = self.manager.list_running()
        self.assertNotIn("dummy_worker", running)

    def test_shutdown_all(self):
        # Create a thread that loops until stop_event is set
        stop_flag = threading.Event()
        
        def worker_loop(event):
            while not event.is_set():
                time.sleep(0.01)

        thread = threading.Thread(target=worker_loop, args=(stop_flag,))
        thread.start()

        def stop_fn():
            stop_flag.set()

        self.manager.register("stoppable_worker", thread, stop_fn=stop_fn)
        
        self.assertIn("stoppable_worker", self.manager.list_running())
        
        results = self.manager.shutdown_all(timeout=1.0)
        
        self.assertTrue(results.get("stoppable_worker", False))
        self.assertEqual(len(self.manager.list_running()), 0)
        self.assertFalse(thread.is_alive())

    def test_unregister(self):
        thread = threading.Thread(target=lambda: time.sleep(0.5))
        thread.start()
        self.manager.register("temp_worker", thread)
        
        self.assertIsNotNone(self.manager.get_worker("temp_worker"))
        
        self.manager.unregister("temp_worker")
        self.assertIsNone(self.manager.get_worker("temp_worker"))
        thread.join()

if __name__ == '__main__':
    unittest.main()
