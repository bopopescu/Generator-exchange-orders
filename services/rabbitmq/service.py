from __future__ import unicode_literals
from services.rabbitmq.connection import *
from configurations.messageconfigs import *
from reporter import *
from models.OrdersObject import *
from utils.timeit import *
from services.proto.orderinfo_pb2 import OrderInfo
from services.database.mysql.service import *


class RMQService:
    def __init__(self):
        self.conn = RMQConnection()
        self.properties = MessageConfigs()
        self.stopmsgcount = 0
        self.consumeddata = []
        self.consumedbatch = 1

    def startSending(self):
        log.INFO("Sending records to RabbitMQ started.")
        try:
            if self.__open_connection(host=self.properties.rmq_host, port=self.properties.rmq_port,
                                 virtual_host=self.properties.rmq_vhost, user=self.properties.rmq_user,
                                 password=self.properties.rmq_password):
                self.__delete_exchange(exchange_name=self.properties.rmq_exchange_name)
                self.__declare_exchange(exchange_name=self.properties.rmq_exchange_name,
                                     exchange_type=self.properties.rmq_exchange_type)
            else:
                return False
        except ValueError as err:
            log.ERROR("Occured while preparing exchange to send messages to Rmq. {}".format(str(err)))
            return False
        try:
            self.__declare_queue(queue_name="Red", durable=True)
            self.__declare_queue(queue_name="Green", durable=True)
            self.__declare_queue(queue_name="Blue", durable=True)

            self.__queue_bind("Red", self.properties.rmq_exchange_name, self.properties.rmq_red_routing_key)
            self.__queue_bind("Green", self.properties.rmq_exchange_name, self.properties.rmq_green_routing_key)
            self.__queue_bind("Blue", self.properties.rmq_exchange_name, self.properties.rmq_blue_routing_key)

            self.__queue_purge("Red")
            self.__queue_purge("Green")
            self.__queue_purge("Blue")
        except Exception as err:
            log.ERROR("Occured while preparing queues to send messages to Rmq. {}".format(str(err)))
            return False
        return True

    def stopSending(self):
        try:
            self.__publish(self.properties.rmq_exchange_name, self.properties.rmq_blue_routing_key, "endofhistory")
            self.__publish(self.properties.rmq_exchange_name, self.properties.rmq_red_routing_key, "endofhistory")
            self.__publish(self.properties.rmq_exchange_name, self.properties.rmq_green_routing_key, "endofhistory")
            Reporter().sendmsgcount += 3
            log.INFO("Sending records to RabbitMQ stopped.")
            self.__close_connnection()
        except pika.exceptions.AMQPError as err:
            log.ERROR(str(err))


    @timeit
    def sendObjects(self, objects, key):
        if self.conn.isconnected is True:
            if key == "Red":
                key = self.properties.rmq_red_routing_key
            elif key == "Green":
                key = self.properties.rmq_green_routing_key
            elif key == "Blue":
                key = self.properties.rmq_blue_routing_key

            for one in objects:
                self.__publish(exchange_name=self.properties.rmq_exchange_name, routing_key=key, body=one)
                Reporter().sendmsgcount += 1
            self.__publish(exchange_name=self.properties.rmq_exchange_name, routing_key=key, body="endofbatch")
            Reporter().sendmsgcount += 1

    def startConsuming(self):
        try:
            self.__open_connection(host=self.properties.rmq_host, port=self.properties.rmq_port,
                                 virtual_host=self.properties.rmq_vhost, user=self.properties.rmq_user,
                                 password=self.properties.rmq_password)
        except ValueError as err:
            log.ERROR("Occured while preparing connection for consuming messages to Rmq. {}".format(str(err)))
            return False

        log.INFO("Start consuming records from RabbitMQ.")

        self.__basic_qos(prefetch_count=1)
        self.__consume(queue_name="Red", on_consume_callback=self.__consumedcallback)
        self.__consume(queue_name="Blue", on_consume_callback=self.__consumedcallback)
        self.__consume(queue_name="Green", on_consume_callback=self.__consumedcallback)

        self.mysql = MySqlService(nowopen=True)

        if self.__start_consuming() is False:
            self.__reconnection()
            self.startConsuming()


    def stopConsuming(self):
        log.INFO("Consuming is finished. Messages count = {}".format(Reporter().consumedmsgcount))
        log.INFO("Rows are inserted into table. There are {} records".format(Reporter().insertrowscount))
        self.__stop_consuming()

    def __consumedcallback(self, channel, method, header, body):
        Reporter().consumedmsgcount += 1
        if body == b'endofbatch':
            log.DEBUG("Consumed {} messages.".format(len(self.consumeddata)))
            self.consumedbatch += 1
            self.mysql.insertConsumedObjects(self.consumeddata, True)
            self.consumeddata.clear()
        elif body == b'endofhistory':
            self.stopmsgcount += 1
            if self.stopmsgcount == 3:
                self.stopConsuming()
        else:
            order_record = OrderInfo()
            order_record.ParseFromString(body)

            data = OrdersObject(createnow=False)
            data.setFromObject(order_record)

            self.consumeddata.append(data)

        channel.basic_ack(delivery_tag=method.delivery_tag)

    def __open_connection(self, user=pika.connection.Parameters.DEFAULT_USERNAME,
                    password=pika.connection.Parameters.DEFAULT_PASSWORD,
                    host=pika.connection.Parameters.DEFAULT_HOST,
                    port=pika.connection.Parameters.DEFAULT_PORT, *args, **kwargs):
        if 'vhost' in kwargs:
            vhost = kwargs['vhost']
        else:
            vhost = pika.connection.Parameters.DEFAULT_VIRTUAL_HOST

        log.TRACE("Connecting to RMQ")
        self.conn.open(host=host, port=port, user=user, password=password, virtual_host=vhost)

        return self.conn.isconnected

    def __close_connnection(self):
        log.TRACE("Closing RMQ connection")
        self.conn.close()

    def __reconnection(self):
        self.__close_connnection()
        for i in range(1, 5):
            if not self.__open_connection(host=self.properties.rmq_host, port=self.properties.rmq_port,
                                          virtual_host=self.properties.rmq_vhost, user=self.properties.rmq_user,
                                          password=self.properties.rmq_password):
                log.DEBUG("Trying reconnect in {}s".format(i * 2))
                time.sleep(i * 2)
            else:
                log.DEBUG("Successfully reconnected.")
                return True
        log.CRITICAL("Lost connection to RabbitMQ. Quiting...")
        sys.exit(0)

    def __publish(self, exchange_name, routing_key, body, properties=pika.BasicProperties(delivery_mode=2), mandatory=False):
        if not self.conn.publish(exchange_name, routing_key, body, properties=properties, mandatory=mandatory):
            self.__reconnection()

    def __declare_exchange(self, exchange_name, exchange_type, passive=False, durable=True, auto_delete=False):
        log.TRACE("Trying to create exchange '{}' type '{}'".format(exchange_name, exchange_type))
        return self.conn.declare_exchange(exchange_name, exchange_type, passive=passive, durable=durable, auto_delete=auto_delete)

    def __declare_queue(self, queue_name, durable=False):
        log.TRACE("Trying to declare {} queue '{}'".format("durable" if durable else "", queue_name))
        return self.conn.declare_queue(queue_name=queue_name, durable=durable)

    def __delete_queue(self, queue_name, if_unused=False, if_empty=False):
        log.TRACE("Deleting queue '{}'".format(queue_name))
        return self.conn.delete_queue(queue_name, if_unused=if_unused, if_empty=if_empty)

    def __delete_exchange(self, exchange_name=None, if_unused=False):

        log.TRACE("Deleting exchange '{}'".format(exchange_name))
        return self.conn.delete_exchange(exchange_name=exchange_name, if_unused=if_unused)

    def __queue_bind(self, queue_name, exchange_name, routing_key=None):

        log.TRACE("Binding queue '{}' to exchange '{}' with routing key  '{}'".format(queue_name, exchange_name,
                                                                                             routing_key))
        return self.conn.bind_queue(queue_name=queue_name, exchange_name=exchange_name, routing_key=routing_key)

    def __queue_unbind(self, queue_name, exchange_name, routing_key=None):
        log.TRACE("Unbinding queue '{}' from exchange '{}' with routing key  '{}'".format(queue_name, exchange_name,
                                                                                       routing_key))
        return self.conn.unbind_queue(queue_name=queue_name, exchange_name=exchange_name, routing_key=routing_key)

    def __queue_purge(self, queue_name):
        log.TRACE('Purging queue {}'.format(queue_name))
        return self.conn.purge_queue(queue_name)

    def __exchange_bind(self, destination, source, routing_key=''):
        log.TRACE("Binding exchange: destination '{}', source '{}', routing_key '{}'".format(destination, source, routing_key))
        return self.conn.bind_exchange(destination=destination, source=source, routing_key=routing_key)

    def __exchange_unbind(self, destination, source, routing_key=''):
        log.TRACE("Unbinding exchange: destination '{}', source '{}', routing_key '{}'".format(destination, source, routing_key))
        return self.conn.unbind_exchange(destination=destination, source=source, routing_key=routing_key)

    def __consume(self, queue_name, on_consume_callback):
        log.TRACE("Consuming: queue_name '{}', on_consume_callback '{}'".format(queue_name, on_consume_callback))
        self.conn.consume(queue_name=queue_name, on_consume_callback=on_consume_callback)

    def __start_consuming(self):
        log.INFO("Consuming started.")
        return self.conn.start_consuming()


    def __stop_consuming(self):
        if self.conn.stop_consuming():
            log.TRACE("Consuming stopped.")

    def __basic_qos(self, prefetch_count):
        return self.conn.basic_qos(prefetch_count=prefetch_count)
        pass
