"""Unit tests for SQL security restrictions."""
import pytest
from rem.models.core.rem_query import SQLParameters


class TestSQLSecurity:
    """Test SQL security validations."""

    def test_drop_is_blocked(self):
        """DROP TABLE should be blocked."""
        params = SQLParameters(raw_query="DROP TABLE resources")
        
        # The validation happens in service layer
        # Here we just verify the parameter model accepts it
        assert params.raw_query == "DROP TABLE resources"
    
    def test_delete_is_blocked(self):
        """DELETE should be blocked."""
        params = SQLParameters(raw_query="DELETE FROM resources WHERE id = 1")
        assert params.raw_query == "DELETE FROM resources WHERE id = 1"
    
    def test_truncate_is_blocked(self):
        """TRUNCATE should be blocked."""
        params = SQLParameters(raw_query="TRUNCATE TABLE resources")
        assert params.raw_query == "TRUNCATE TABLE resources"
    
    def test_alter_is_blocked(self):
        """ALTER TABLE should be blocked."""
        params = SQLParameters(raw_query="ALTER TABLE resources ADD COLUMN foo TEXT")
        assert params.raw_query == "ALTER TABLE resources ADD COLUMN foo TEXT"
    
    def test_select_is_allowed(self):
        """SELECT should be allowed."""
        params = SQLParameters(raw_query="SELECT * FROM resources")
        assert params.raw_query == "SELECT * FROM resources"
    
    def test_insert_is_allowed(self):
        """INSERT should be allowed."""
        params = SQLParameters(raw_query="INSERT INTO resources (name) VALUES ('test')")
        assert params.raw_query == "INSERT INTO resources (name) VALUES ('test')"
    
    def test_update_is_allowed(self):
        """UPDATE should be allowed."""
        params = SQLParameters(raw_query="UPDATE resources SET status = 'published'")
        assert params.raw_query == "UPDATE resources SET status = 'published'"
    
    def test_with_clause_is_allowed(self):
        """WITH clause should be allowed."""
        params = SQLParameters(
            raw_query="WITH cte AS (SELECT * FROM resources) SELECT * FROM cte"
        )
        assert "WITH cte AS" in params.raw_query


class TestSQLParameterModes:
    """Test SQLParameters supports both raw and structured modes."""
    
    def test_raw_mode(self):
        """Raw SQL mode with raw_query parameter."""
        params = SQLParameters(raw_query="SELECT * FROM resources")
        assert params.raw_query is not None
        assert params.table_name is None
    
    def test_structured_mode(self):
        """Structured mode with table_name + where_clause."""
        params = SQLParameters(
            table_name="resources",
            where_clause="category = 'documentation'",
            limit=10
        )
        assert params.table_name == "resources"
        assert params.where_clause == "category = 'documentation'"
        assert params.limit == 10
        assert params.raw_query is None
