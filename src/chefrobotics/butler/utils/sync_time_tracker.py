import fcntl
import json
import tempfile
import time
from pathlib import Path

from chefrobotics.butler.utils.db_utils import get_butler_db_dir

# If first time syncing, do not sync more than one week ago
DEFAULT_MIN_SYNC_TIME = int(time.time()) - (7 * 24 * 60 * 60)


class SyncTimeTracker:
    def __init__(self):
        self._push_sync_time = DEFAULT_MIN_SYNC_TIME
        self._pull_sync_time = DEFAULT_MIN_SYNC_TIME
        self._sync_file_path = (
            Path(get_butler_db_dir()) / "sync_timestamps.json"
        )

        # Ensure parent directory exists
        self._sync_file_path.parent.mkdir(parents=True, exist_ok=True)

        self._load_from_file()

    def _load_from_file(self):
        """Load sync timestamps from file with error handling.

        If any error occurs during file operations or parsing,
        timestamps will remain at their default values (0).
        If the file doesn't exist, it will be created with default values.
        """

        if not self._sync_file_path.exists():
            print("Sync file does not exist, creating with default values")
            try:
                # Create file with default values
                default_data = {
                    "push": self._push_sync_time,
                    "pull": self._pull_sync_time,
                }
                with open(self._sync_file_path, "w") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        json.dump(default_data, f)
                        f.flush()
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return
            except Exception as e:
                return

        try:
            with open(self._sync_file_path) as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.loads(f.read())
                    self._push_sync_time = int(data.get("push", 0))
                    self._pull_sync_time = int(data.get("pull", 0))
                except Exception as e:
                    print(f"Error reading sync file: {e}")
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            print(f"Error accessing sync file: {e}")

    def _save_to_file(self):
        # Create temporary file in same directory
        with tempfile.NamedTemporaryFile(
            mode="w", dir=str(self._sync_file_path.parent), delete=False
        ) as tf:
            # Acquire exclusive lock for writing
            fcntl.flock(tf.fileno(), fcntl.LOCK_EX)
            try:
                # Write data to temporary file
                data = {
                    "push": self._push_sync_time,
                    "pull": self._pull_sync_time,
                }
                json.dump(data, tf)
                tf.flush()  # Ensure all data is written
                temp_path = Path(tf.name)
            finally:
                fcntl.flock(tf.fileno(), fcntl.LOCK_UN)

        try:
            # Atomically replace the target file
            temp_path.rename(self._sync_file_path)
        except OSError as e:
            # Clean up temp file if rename fails
            temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to save sync timestamps: {e}")

    def get_push_sync_time(self) -> int:
        return self._push_sync_time

    def get_pull_sync_time(self) -> int:
        return self._pull_sync_time

    def update_push_sync_time(self, timestamp: float):
        self._push_sync_time = int(timestamp)
        self._save_to_file()

    def update_pull_sync_time(self, timestamp: float):
        self._pull_sync_time = int(timestamp)
        self._save_to_file()
