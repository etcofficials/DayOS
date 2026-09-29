"""Bundles the database, repositories and settings for the UI."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import AppPaths
from src.database import Database, init_database
from src.repositories.exams import ExamRepository
from src.repositories.goals import GoalRepository, JournalRepository
from src.repositories.habits import HabitRepository
from src.repositories.notes import NoteRepository
from src.repositories.schedule import ScheduleRepository
from src.repositories.study import StudyRepository
from src.repositories.subjects import SubjectRepository
from src.repositories.tasks import TaskRepository
from src.services.settings import Settings


@dataclass
class AppContext:
    paths: AppPaths
    db: Database
    settings: Settings
    subjects: SubjectRepository
    tasks: TaskRepository
    notes: NoteRepository
    habits: HabitRepository
    goals: GoalRepository
    journal: JournalRepository
    schedule: ScheduleRepository
    study: StudyRepository
    exams: ExamRepository

    @classmethod
    def open(cls, paths: AppPaths) -> "AppContext":
        db = init_database(paths.db_path, paths.backups_dir)
        return cls.from_db(paths, db)

    @classmethod
    def from_db(cls, paths: AppPaths, db: Database) -> "AppContext":
        return cls(
            paths=paths,
            db=db,
            settings=Settings(db),
            subjects=SubjectRepository(db),
            tasks=TaskRepository(db),
            notes=NoteRepository(db),
            habits=HabitRepository(db),
            goals=GoalRepository(db),
            journal=JournalRepository(db),
            schedule=ScheduleRepository(db),
            study=StudyRepository(db),
            exams=ExamRepository(db),
        )

    def close(self) -> None:
        self.db.close()
