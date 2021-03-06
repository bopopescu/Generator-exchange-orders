from __future__ import unicode_literals
import mysql.connector
from services.database.dbconnection import *
from loger import *
log = Logger()

# Please catch Exceptions and Errors outside

class MySqlConnection(DbConnection):
    def __init__(self, host, user, password, dbname):
        DbConnection.__init__(self, host, user, password, dbname)
        self.__curs = None

    def cursor(self, buffered=None, raw=None, prepared=None, cursor_class=None, dictionary=None, named_tuple=None):
        if self.isconnected:
            if self.__curs is None:
                log.TRACE("Setting cursor for '{}'.".format(self.dbname))
                self.__curs = self.conn.cursor(buffered, raw, prepared, cursor_class, dictionary, named_tuple)
                log.TRACE("Successfully set.")
                return self.__curs
            else:
                return self.__curs
        else:
            log.ERROR("Can not get cursor because connection is unset.")

    def connect(self):
        if self.isconnected is True:
            log.DEBUG("Connection to database '{}' is Success.".format(self.dbname))
        else:
            log.TRACE("Trying to open new connection.")
            try:
                self.__curs = None
                self.conn = self.__createConnection()
                self.isconnected = True
                self.connect()
            except mysql.connector.Error as err:
                log.ERROR("Unable to connect to {}".format(self.getConnectionString(dbconnect=True)))
                self.isconnected = False
                raise err

    def commit(self):
        if self.isconnected:
            self.conn.commit()
            return True
        else:
            return False

    def reconnect(self):
        self.disconnect()
        self.connect()

    def disconnect(self):
        if self.isconnected is True:
            self.conn.close()
            self.isconnected = False
            log.TRACE("Disconnected from mysql - Success.")
            return True
        log.TRACE("It is already disconnected.")

    def __openConnection(self):
        return mysql.connector.connect(host=self.host, user=self.user, password=self.password, database=self.dbname,
                                       auth_plugin='mysql_native_password')



    def __createConnection(self):
        try:
            cnx = self.__openConnection()
            log.DEBUG("Connection to {} is Success.".format(self.getConnectionString(dbconnect=True)))
            return cnx
        except mysql.connector.Error as err:
            raise err
