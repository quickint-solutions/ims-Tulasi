"""Package init.

On shared hosting (cPanel) the MySQL driver is PyMySQL, because `mysqlclient`
needs a C compiler and MySQL headers that shared hosts almost never provide.
Registering it as MySQLdb here - before Django loads its MySQL backend - lets the
standard `django.db.backends.mysql` engine use it unchanged.

Harmless everywhere else: if PyMySQL is not installed, nothing happens.
"""
try:  # pragma: no cover - depends on the deployment target
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:
    pass
