from guardmcp.plugins.mongodb.client import MongoClient


class _FakeDb:
    """Fake database object that records (dbname, collection) pairs."""
    def __init__(self, dbname):
        self.dbname = dbname

    def __getitem__(self, coll):
        return (self.dbname, coll)


class _FakeMotor:
    """Fake Motor client: client[name] -> _FakeDb(name)."""
    def __getitem__(self, name):
        return _FakeDb(name)


def _client():
    c = MongoClient.__new__(MongoClient)  # bypass real connection
    c._client = _FakeMotor()
    c._db = _FakeDb("configured")
    return c


def test_get_db_default_returns_configured():
    c = _client()
    assert c.get_db().dbname == "configured"
    assert c.get_db(None).dbname == "configured"


def test_get_db_named_returns_that_db():
    c = _client()
    assert c.get_db("other").dbname == "other"


def test_get_collection_routes_by_database():
    c = _client()
    assert c.get_collection("mycoll", database="other") == ("other", "mycoll")


def test_get_collection_default_database():
    c = _client()
    assert c.get_collection("mycoll") == ("configured", "mycoll")
