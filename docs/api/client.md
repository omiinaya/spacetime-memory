# Client API

The central interface to Spacetime Memory. The `Client` class is composed
from domain-specific mixins:

```python
from spacetime_memory import Client

c = Client(host="127.0.0.1", port="3001", database="my-db")
```

::: spacetime_memory.client
