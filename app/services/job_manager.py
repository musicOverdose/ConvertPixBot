"""Generic Job Lifecycle Manager with isolated workspaces and auto-cleanup."""

import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
import shutil
import time
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)


class JobLimitError(Exception):
    """Raised when job limits are exceeded."""
    pass


class UserConcurrentJobLimitError(JobLimitError):
    """Raised when a user exceeds their concurrent job quota."""
    pass


class GlobalConcurrentJobLimitError(JobLimitError):
    """Raised when the global job capacity is reached."""
    pass


class MaintenanceModeError(JobLimitError):
    """Raised when new jobs cannot be accepted due to maintenance."""
    pass


@dataclass
class Job:
    """Represents an isolated processing session."""
    uuid: str
    user_id: int
    chat_id: int = 0
    original_filename: str = 'input.dat'
    file_size_bytes: int = 0
    dir_path: Path = field(default_factory=Path)
    status: str = 'active'
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    @property
    def workspace_dir(self) -> Path:
        return self.dir_path

    @property
    def original_path(self) -> Path:
        return self.dir_path / self.original_filename

    def touch(self) -> None:
        self.last_activity = time.time()


class JobManager:
    """Manages job sessions, temporary directory workspaces, and life-cycle events."""

    def __init__(
        self,
        base_jobs_dir: Path,
        ttl_minutes: int = 30,
        max_user_concurrent_jobs: int = 1,
        max_global_concurrent_jobs: int = 10,
    ) -> None:
        self.base_jobs_dir = Path(base_jobs_dir)
        self.ttl_seconds = ttl_minutes * 60
        self.max_user_concurrent_jobs = max_user_concurrent_jobs
        self.max_global_concurrent_jobs = max_global_concurrent_jobs
        self._jobs: Dict[str, Job] = {}
        self._maintenance_mode: bool = False

        self.base_jobs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def active_jobs(self) -> Dict[str, Job]:
        return dict(self._jobs)

    def get_active_jobs_count(self) -> int:
        return len(self._jobs)

    @property
    def is_maintenance_mode(self) -> bool:
        return self._maintenance_mode

    def set_maintenance_mode(self, enabled: bool) -> None:
        self._maintenance_mode = enabled
        logger.info(f'Maintenance mode set to {enabled}')

    def get_job(self, job_uuid: str) -> Optional[Job]:
        job = self._jobs.get(job_uuid)
        if job:
            job.touch()
        return job

    def get_user_active_job(self, user_id: int) -> Optional[Job]:
        for job in self._jobs.values():
            if job.user_id == user_id:
                job.touch()
                return job
        return None

    def get_user_active_job_count(self, user_id: int) -> int:
        return sum(1 for j in self._jobs.values() if j.user_id == user_id)

    def create_job(
        self,
        user_id: int,
        original_filename: str,
        file_size_bytes: int = 0,
        chat_id: int = 0,
    ) -> Job:
        if self._maintenance_mode:
            raise MaintenanceModeError('Bot is currently under maintenance. Please try again later.')

        if len(self._jobs) >= self.max_global_concurrent_jobs:
            raise GlobalConcurrentJobLimitError('Server is currently at maximum capacity. Please retry shortly.')

        user_count = self.get_user_active_job_count(user_id)
        if user_count >= self.max_user_concurrent_jobs:
            raise UserConcurrentJobLimitError(
                f'You already have {user_count} active job(s). Please wait for them to finish.'
            )

        job_uuid = str(uuid.uuid4())
        job_dir = self.base_jobs_dir / job_uuid
        job_dir.mkdir(parents=True, exist_ok=True)

        job = Job(
            uuid=job_uuid,
            user_id=user_id,
            chat_id=chat_id,
            original_filename=original_filename,
            file_size_bytes=file_size_bytes,
            dir_path=job_dir,
        )

        self._jobs[job_uuid] = job
        logger.info(f'Created job {job_uuid} for user {user_id} at {job_dir}')
        return job

    def cleanup_job(self, job_uuid: str) -> bool:
        job = self._jobs.pop(job_uuid, None)
        job_dir = self.base_jobs_dir / job_uuid
        if job_dir.exists():
            try:
                shutil.rmtree(job_dir, ignore_errors=True)
                logger.debug(f'Deleted workspace for job {job_uuid}')
            except Exception as e:
                logger.warning(f'Failed to delete directory {job_dir}: {e}')
        return job is not None

    def cleanup_expired_jobs(self) -> int:
        now = time.time()
        expired = [
            uuid_str
            for uuid_str, job in self._jobs.items()
            if (now - job.last_activity) > self.ttl_seconds
        ]
        for uuid_str in expired:
            logger.info(f'Expiring job {uuid_str} due to inactivity (TTL={self.ttl_seconds}s)')
            self.cleanup_job(uuid_str)
        return len(expired)

    def cleanup_orphaned_job_dirs(self) -> int:
        if not self.base_jobs_dir.exists():
            return 0
        cleaned = 0
        for entry in self.base_jobs_dir.iterdir():
            if entry.is_dir() and entry.name not in self._jobs:
                try:
                    shutil.rmtree(entry, ignore_errors=True)
                    cleaned += 1
                except Exception as e:
                    logger.warning(f'Could not remove orphaned dir {entry}: {e}')
        return cleaned

    def get_temp_disk_usage_mb(self) -> float:
        """Calculates total disk usage in megabytes across temporary job directories."""
        if not self.base_jobs_dir.exists():
            return 0.0
        total_bytes = 0
        try:
            for p in self.base_jobs_dir.rglob('*'):
                if p.is_file():
                    try:
                        total_bytes += p.stat().st_size
                    except OSError:
                        pass
        except Exception as e:
            logger.warning(f'Error calculating disk usage: {e}')
        return round(total_bytes / (1024 * 1024), 2)
