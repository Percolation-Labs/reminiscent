# Python Best Practices

Writing clean, maintainable Python code requires following established conventions.

## Code Style

### PEP 8 Guidelines
- Use 4 spaces for indentation (never tabs)
- Maximum line length: 79 characters for code, 72 for docstrings
- Use snake_case for functions and variables
- Use PascalCase for classes
- Constants in UPPER_CASE

### Type Hints
Modern Python uses type annotations for better IDE support and catching bugs:

```python
from typing import List, Dict, Optional

def process_data(items: List[str], config: Dict[str, any]) -> Optional[str]:
    if not items:
        return None
    return items[0]
```

## Design Patterns

### Context Managers
Use `with` statements for resource management:
```python
with open('file.txt') as f:
    data = f.read()
# File automatically closed
```

### Decorators
Modify function behavior without changing source code:
```python
@lru_cache(maxsize=128)
def expensive_function(n):
    # Cached result
    return compute(n)
```

### Dataclasses
Reduce boilerplate for data-holding classes:
```python
from dataclasses import dataclass

@dataclass
class User:
    name: str
    email: str
    age: int
```

## Testing

### Pytest Framework
```python
def test_addition():
    assert add(2, 3) == 5

def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(10, 0)
```

### Fixtures
Reusable setup code:
```python
@pytest.fixture
def database():
    db = Database()
    db.connect()
    yield db
    db.disconnect()
```

## Performance Optimization
- Use list comprehensions instead of loops
- Leverage built-in functions (sum, min, max)
- Profile code with cProfile before optimizing
- Consider numpy for numerical operations
- Use asyncio for I/O-bound tasks
