from typing import Callable
from typing import TypeVar

from fastapi import HTTPException
from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

T = TypeVar("T")  # Generic type for return values


class DatabaseManager:
    # TODO: (Charvi) Add __enter__ and __exit__ methods to handle sessions
    # i.e. make this a context manager
    def __init__(self, engine):
        self.engine = engine

    def execute_transaction(self, operation: Callable[[Session], T]) -> T:
        """Execute a database transaction with error handling.

        Args:
            operation: Callable that takes a database session and returns a result

        Returns:
            The result of the operation

        Raises:
            HTTPException: On database errors
        """
        with Session(self.engine) as session:
            try:
                result = operation(session)
                session.commit()
                return result
            except IntegrityError as ie:
                session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Database integrity error: {str(ie)}",
                )
            except SQLAlchemyError as sae:
                session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Database error: {str(sae)}",
                )

    def execute_query(self, operation: Callable[[Session], T]) -> T:
        """Execute a read-only database query with error handling.

        Args:
            operation: Callable that takes a database session and returns a result

        Returns:
            The result of the operation

        Raises:
            HTTPException: On database errors
        """
        with Session(self.engine) as session:
            try:
                return operation(session)
            except SQLAlchemyError as sae:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Database error: {str(sae)}",
                )
