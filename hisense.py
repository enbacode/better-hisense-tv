import asyncio
import re
import uuid
import hashlib
import time
import json
import logging
import paho.mqtt.client as mqtt
from pprint import pprint
import keyboard 
import argparse
import os
import sys
import random

script_directory = os.path.dirname(os.path.abspath(sys.argv[0]))

# Configuration
tv_ip = "192.168.178.25"
random_mac = True # Set to False if you want to use a specific MAC address
certfile = os.path.join(script_directory, "./rcm_certchain_pem.cer")
keyfile = os.path.join(script_directory, "./rcm_pem_privkey.pkcs8")
# certfile = os.path.join(script_directory, "./vidaa_cert.cer")
# keyfile = os.path.join(script_directory, "./vidaa_cert.pkcs8")
credentialsfile = os.path.join(script_directory, "credentials.json") 
auth_numfile = "./authcode.txt"  # Temporary file to store the code
check_interval = 0.1
debug = True
new_auth = False
file_auth = False

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TVAuthenticator:
    def __init__(
        self,
        tv_ip,
        certfile,
        keyfile,
    ):
        
        self.tv_ip = tv_ip
        self.certfile = certfile
        self.keyfile = keyfile

        self.check_interval = 0.1
        self.debug = True
        self.new_auth = False
        self.file_auth = False

        self.reply = None
        self.authentication_payload = None
        self.authentication_code_payload = None
        self.tokenissuance = None
        self.accesstoken = None
        self.accesstoken_time = None
        self.accesstoken_duration_day = None
        self.refreshtoken = None
        self.refreshtoken_time = None
        self.refreshtoken_duration_day = None
        self.client_id = None
        self.username = None
        self.password = None
        self.timestamp = None
        self.authenticated = False

        self.topicTVUIBasepath = None
        self.topicTVPSBasepath = None
        self.topicMobiBasepath = None
        self.topicBrcsBasepath = None
        self.topicRemoBasepath = None

        self.info = None

        self.client = mqtt.Client()

    @staticmethod
    # Sum all digits of a number
    def cross_sum(n):
        return sum(int(digit) for digit in str(n))

    @staticmethod
    # Convert a string to a hash
    def string_to_hash(input_str):
        return hashlib.md5(input_str.encode("utf-8")).hexdigest().upper()

    # Action when connected
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.connected_flag = True
            logging.info("Connected to MQTT broker")
        else:
            logging.error(f"Bad connection. Returned code: {rc}")
            client.cancel_loop = True

    # Action when message received
    def on_message(self, client, userdata, msg):
        logging.info(f"Message received: {msg.payload.decode('utf-8')} on topic {msg.topic}")
        self.authenticated = False
        self.reply = msg

    # Action when subscribed
    def on_subscribe(self, client, userdata, mid, granted_qos):
        logging.info(f"Subscribed: {mid} {granted_qos}")

    # Action when published
    def on_publish(self, client, userdata, mid):
        logging.info(f"Published message {mid}")

    # Action when disconnected
    def on_disconnect(self, client, userdata, rc):
        logging.info(f"Disconnected. Reason: {rc}")
        client.cancel_loop = True

    # Action when authentication message received
    def on_authentication(self, mosq, obj, msg):
        logging.info(f"Authentication message received: {msg.payload.decode('utf-8')} on topic {msg.topic}")
        self.authentication_payload = msg

    # Action when authentication code message received
    def on_authentication_code(self, mosq, obj, msg):
        logging.info(f"Authentication code message received: {msg.payload.decode('utf-8')} on topic {msg.topic}")
        self.authentication_code_payload = msg

    # Action when token issuance message received
    def on_tokenissuance(self, mosq, obj, msg):
        logging.info(f"Token issuance message received: {msg.payload.decode('utf-8')} on topic {msg.topic}")
        self.tokenissuance = msg

    # Action when information message received
    def on_info(self, mosq, obj, msg):
        logging.info(f"Information message received: {msg.payload.decode('utf-8')} on topic {msg.topic}")
        self.info = msg.payload.decode('utf-8')

    # Wait for a message (condition is a lambda function that returns True or False)
    async def wait_for_message(self, condition, check_interval=1, debug=False):
        initial_start_time = time.time()
        timeout = 60  # Maximum wait time in seconds
        logging.info("Waiting for message... (press and hold escape to cancel waiting)")
        await asyncio.sleep(1)  # Initial delay to prevent false negatives

        logging.info("Waiting...")
        while condition():
            # only add a dot every 3 seconds
            current_time = time.time()

            # check if timeout is reached
            if current_time - initial_start_time >= timeout:
                logging.info("\nTimeout reached. Exiting...")
                break

            # wait a bit before checking again
            await asyncio.sleep(check_interval)
    
    def initialize_client(self):
        logging.info("Creating MQTT client...")
        client = mqtt.Client(client_id=self.client_id, clean_session=True, userdata=self.userdata, protocol=mqtt.MQTTv311, transport="tcp")
        client.tls_set(ca_certs=None, certfile=self.certfile, keyfile=self.keyfile, cert_reqs=mqtt.ssl.CERT_NONE, tls_version=mqtt.ssl.PROTOCOL_TLS)
        client.tls_insecure_set(True)
        client.username_pw_set(username=self.username, password=self.password)
        
        # Attach event handlers
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.on_publish = self.on_publish
        client.on_disconnect = self.on_disconnect
        client.enable_logger()

        client.connected_flag = False
        client.cancel_loop = False

        return client

    # Open the client and connect to the TV
    def create_mqtt_client(self, client_id, certfile, keyfile, username, password, userdata=None):
        logging.info("Creating MQTT client...")
        client = mqtt.Client(client_id=client_id, clean_session=True, userdata=userdata, protocol=mqtt.MQTTv311, transport="tcp")
        client.tls_set(ca_certs=None, certfile=certfile, keyfile=keyfile, cert_reqs=mqtt.ssl.CERT_NONE, tls_version=mqtt.ssl.PROTOCOL_TLS)
        client.tls_insecure_set(True)
        client.username_pw_set(username=username, password=password)

        # Attach event handlers
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.on_publish = self.on_publish
        client.on_disconnect = self.on_disconnect
        client.enable_logger()

        client.connected_flag = False
        client.cancel_loop = False

        return client

    # Refresh the token
    async def refresh_token(self):
        logging.info("Refreshing token...")

        client = self.create_mqtt_client(client_id=self.client_id, certfile=certfile, keyfile=keyfile, username=self.username, password=self.refreshtoken)
        logging.info(f"Adding callback message to {self.topicMobiBasepath}platform_service/data/tokenissuance")
        client.message_callback_add(self.topicMobiBasepath + 'platform_service/data/tokenissuance', self.on_tokenissuance)

        client.connect_async(tv_ip, 36669, 60)
        client.loop_start()

        await self.wait_for_message(lambda: not client.connected_flag and not client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        client.subscribe(self.topicMobiBasepath + 'platform_service/data/tokenissuance')
        client.publish(f"/remoteapp/tv/platform_service/{self.client_id}/data/gettoken", json.dumps({"refreshtoken": self.refreshtoken}))

        self.wait_for_message(lambda: self.tokenissuance is None or client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        credentials = json.loads(self.tokenissuance.payload.decode())
        credentials.update({"client_id": self.client_id, "username": self.username, "password": self.password})

        logging.info(f'Token issued successfully! credentials: {credentials}')
        # TODO do we need this?
        # with open(credentialsfile, 'w') as file:
        #     json.dump(credentials, file, indent=4)
        # if debug:
        #     logging.info('Credentials saved to {credentialsfile}')        

        client.loop_stop()
        client.disconnect()

        self.accesstoken = credentials["accesstoken"]
        self.accesstoken_time = credentials["accesstoken_time"]
        self.accesstoken_duration_day = credentials["accesstoken_duration_day"]
        self.refreshtoken = credentials["refreshtoken"]
        self.refreshtoken_time = credentials["refreshtoken_time"]
        self.refreshtoken_duration_day = credentials["refreshtoken_duration_day"]
        self.client_id = credentials['client_id']
        self.username = credentials['username']
        self.password = credentials['password']
        self.authenticated = True

        return credentials["accesstoken"]

    def random_mac_address(self):
        # A MAC address has 6 pairs of hexadecimal digits
        mac = [random.randint(0x00, 0xFF) for _ in range(6)]
        return ':'.join(f'{octet:02x}' for octet in mac)

    # Check and refresh the token if needed
    async def check_and_refresh_token(self):
        current_time = time.time()
        logging.info(f"Current time is {time.ctime(current_time)}")

        expiration_time = int(self.accesstoken_time) + (int(self.accesstoken_duration_day) * 24 * 60 * 60)
        logging.info(f"Access Token expires at {time.ctime(expiration_time)}")

        refresh_expiration_time = int(self.refreshtoken_time) + (int(self.refreshtoken_duration_day) * 24 * 60 * 60)
        logging.info(f"Refresh Token expires at {time.ctime(refresh_expiration_time)}")

        if current_time <= expiration_time:
            logging.info("Token still valid, no need to refresh")
            time_diff = expiration_time - current_time
            days = time_diff // (24 * 60 * 60)
            hours = (time_diff % (24 * 60 * 60)) // (60 * 60)
            minutes = (time_diff % (60 * 60)) // 60
            seconds = time_diff % 60
            logging.info(f"Token expires in {int(days)} days, {int(hours)} hours, {int(minutes)} minutes, and {int(seconds)} seconds")
            return self.accesstoken

        logging.info("Token not valid, refreshing the token")

        return await self.refresh_token()
    
    # Define the hashes, username, password and client_id
    def define_hashes(self):
        self.timestamp = int(time.time())

        if random_mac:
            # generate a random mac-address
            mac = self.random_mac_address()
        else:
            mac = ':'.join(re.findall('..', '%012x' % uuid.getnode())).upper()

        logging.info(f'MAC Address: {mac}')

        first_hash = self.string_to_hash("&vidaa#^app")
        second_hash = self.string_to_hash(f"38D65DC30F45109A369A86FCE866A85B${mac}")
        last_digit_of_cross_sum = self.cross_sum(self.timestamp) % 10
        third_hash = self.string_to_hash(f"his{last_digit_of_cross_sum}h*i&s%e!r^v0i1c9")
        fourth_hash = self.string_to_hash(f"{self.timestamp}${third_hash[:6]}")

        if new_auth:
            self.username = f"his${self.timestamp^6239759785777146216}"
        else:
            self.username = f"his${self.timestamp}"

        self.password = fourth_hash

        logging.info(f'First Hash: {first_hash}')
        logging.info(f'Second Hash: {second_hash}')
        logging.info(f'Third Hash: {third_hash}')
        logging.info(f'Fourth Hash: {fourth_hash}')

        self.client_id = f"{mac}$his${second_hash[:6]}_vidaacommon_001"
        logging.info(f'Client ID: {self.client_id}')

    # Define the topic paths
    def define_topic_paths(self):
        self.topicTVUIBasepath = f"/remoteapp/tv/ui_service/{self.client_id}/"
        self.topicTVPSBasepath = f"/remoteapp/tv/platform_service/{self.client_id}/"
        self.topicMobiBasepath = f"/remoteapp/mobile/{self.client_id}/"
        self.topicBrcsBasepath = f"/remoteapp/mobile/broadcast/"
        self.topicRemoBasepath = f"/remoteapp/tv/remote_service/{self.client_id}/"

    async def request_auth_code(self):
        self.define_hashes()
        self.define_topic_paths()

        client = self.create_mqtt_client(client_id=self.client_id, certfile=certfile, keyfile=keyfile, username=self.username, password=self.password)
        logging.info(f"Adding callback messages for authentication...")
        client.message_callback_add(self.topicMobiBasepath + 'ui_service/data/authentication', self.on_authentication)
        client.message_callback_add(self.topicMobiBasepath + 'ui_service/data/authenticationcode', self.on_authentication_code)
        client.message_callback_add(self.topicBrcsBasepath + 'ui_service/data/hotelmodechange', self.on_message)
        client.message_callback_add(self.topicMobiBasepath + 'platform_service/data/tokenissuance', self.on_tokenissuance)

        client.connect_async(tv_ip, 36669, 60)
        client.loop_start()

        await self.wait_for_message(lambda: not client.connected_flag and not client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        client.subscribe([
            (self.topicBrcsBasepath + 'ui_service/state', 0),
            (self.topicTVUIBasepath + 'actions/vidaa_app_connect', 0),
            (self.topicMobiBasepath + 'ui_service/data/authentication', 0),
            (self.topicMobiBasepath + 'ui_service/data/authenticationcode', 0),
            (self.topicBrcsBasepath + "ui_service/data/hotelmodechange", 0),
            (self.topicMobiBasepath + 'platform_service/data/tokenissuance', 0),
        ])

        logging.info('Publishing message to actions/vidaa_app_connect...')
        client.publish(self.topicTVUIBasepath + "actions/vidaa_app_connect", '{"app_version":2,"connect_result":0,"device_type":"Mobile App"}')

        await self.wait_for_message(lambda: self.authentication_payload is None or client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        if self.authentication_payload.payload.decode() != '""':
            logging.error('Problems with the authentication message!')
            logging.error(self.authentication_payload.payload)
            return

        logging.info(f'Subscribing to {self.topicMobiBasepath}ui_service/data/authenticationcode...')
        client.subscribe(self.topicMobiBasepath + 'ui_service/data/authenticationcode')
        return client
    
    async def confirm_auth_code(self, auth_code, client):
        client.publish(self.topicTVUIBasepath + "actions/authenticationcode", f'{{"authNum":{auth_code}}}')

        await self.wait_for_message(lambda: self.authentication_code_payload is None or client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        payload = json.loads(self.authentication_code_payload.payload.decode())
        if not 'result' in payload or payload['result'] != 1:
        # if json.loads(self.authentication_code_payload.payload.decode()) != {"result": 1, "info": ""}:
            logging.error('Problems with the authentication message!')
            logging.error(self.authentication_code_payload.payload)
            return

        logging.info("Success! Getting access token...")
        client.publish(self.topicTVPSBasepath + "data/gettoken", '{"refreshtoken": ""}')
        client.publish(self.topicTVUIBasepath + "actions/authenticationcodeclose")

        client.subscribe(self.topicBrcsBasepath + 'ui_service/data/hotelmodechange')
        client.subscribe(self.topicMobiBasepath + 'platform_service/data/tokenissuance')

        await self.wait_for_message(lambda: self.tokenissuance is None or client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        credentials = json.loads(self.tokenissuance.payload.decode())
        credentials.update({"client_id": self.client_id, "username": self.username, "password": self.password})
        logging.info(credentials)

        logging.info('Token issued successfully')
        
        client.loop_stop()
        client.disconnect()

        self.accesstoken = credentials["accesstoken"]
        self.accesstoken_time = credentials["accesstoken_time"]
        self.accesstoken_duration_day = credentials["accesstoken_duration_day"]
        self.refreshtoken = credentials["refreshtoken"]
        self.refreshtoken_time = credentials["refreshtoken_time"]
        self.refreshtoken_duration_day = credentials["refreshtoken_duration_day"]
        self.client_id = credentials['client_id']
        self.username = credentials['username']
        self.password = credentials['password']
        self.authenticated = True

        return credentials["accesstoken"]

    # Authenticate with the TV and write the credentials to the credentials file
    async def generate_creds(self):
        self.define_hashes()
        self.define_topic_paths()

        client = self.create_mqtt_client(client_id=self.client_id, certfile=certfile, keyfile=keyfile, username=self.username, password=self.password)
        logging.info(f"Adding callback messages for authentication...")
        client.message_callback_add(self.topicMobiBasepath + 'ui_service/data/authentication', self.on_authentication)
        client.message_callback_add(self.topicMobiBasepath + 'ui_service/data/authenticationcode', self.on_authentication_code)
        client.message_callback_add(self.topicBrcsBasepath + 'ui_service/data/hotelmodechange', self.on_message)
        client.message_callback_add(self.topicMobiBasepath + 'platform_service/data/tokenissuance', self.on_tokenissuance)

        client.connect_async(tv_ip, 36669, 60)
        client.loop_start()

        await self.wait_for_message(lambda: not client.connected_flag and not client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        client.subscribe([
            (self.topicBrcsBasepath + 'ui_service/state', 0),
            (self.topicTVUIBasepath + 'actions/vidaa_app_connect', 0),
            (self.topicMobiBasepath + 'ui_service/data/authentication', 0),
            (self.topicMobiBasepath + 'ui_service/data/authenticationcode', 0),
            (self.topicBrcsBasepath + "ui_service/data/hotelmodechange", 0),
            (self.topicMobiBasepath + 'platform_service/data/tokenissuance', 0),
        ])

        logging.info('Publishing message to actions/vidaa_app_connect...')
        client.publish(self.topicTVUIBasepath + "actions/vidaa_app_connect", '{"app_version":2,"connect_result":0,"device_type":"Mobile App"}')

        await self.wait_for_message(lambda: self.authentication_payload is None or client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        if self.authentication_payload.payload.decode() != '""':
            logging.error('Problems with the authentication message!')
            logging.error(self.authentication_payload.payload)
            return

        logging.info(f'Subscribing to {self.topicMobiBasepath}ui_service/data/authenticationcode...')
        client.subscribe(self.topicMobiBasepath + 'ui_service/data/authenticationcode')

        # TODO this must be handled by HASSIO
        authsuccess = False
        while not authsuccess:
            if file_auth:
                while not os.path.exists(auth_numfile):
                    await asyncio.sleep(1)
                with open(auth_numfile, 'r') as file:
                    auth_num = file.read().strip()
            else:
                auth_num = input("Enter the four digits displayed on your TV: ")

            client.publish(self.topicTVUIBasepath + "actions/authenticationcode", f'{{"authNum":{auth_num}}}')

            await self.wait_for_message(lambda: self.authentication_code_payload is None or client.cancel_loop)
            if client.cancel_loop:
                logging.error("Failed to connect to MQTT broker. Exiting...")
                client.loop_stop()
                client.disconnect()
                return

            payload = json.loads(self.authentication_code_payload.payload.decode())
            if not 'result' in payload or payload['result'] != 1:
            # if json.loads(self.authentication_code_payload.payload.decode()) != {"result": 1, "info": ""}:
                logging.error('Problems with the authentication message!')
                logging.error(self.authentication_code_payload.payload)
            else:
                authsuccess = True

            logging.info("Success! Getting access token...")
        client.publish(self.topicTVPSBasepath + "data/gettoken", '{"refreshtoken": ""}')
        client.publish(self.topicTVUIBasepath + "actions/authenticationcodeclose")

        client.subscribe(self.topicBrcsBasepath + 'ui_service/data/hotelmodechange')
        client.subscribe(self.topicMobiBasepath + 'platform_service/data/tokenissuance')

        await self.wait_for_message(lambda: self.tokenissuance is None or client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        credentials = json.loads(self.tokenissuance.payload.decode())
        credentials.update({"client_id": self.client_id, "username": self.username, "password": self.password})
        logging.info(credentials)

        logging.info('Token issued successfully')
        
        client.loop_stop()
        client.disconnect()

        self.accesstoken = credentials["accesstoken"]
        self.accesstoken_time = credentials["accesstoken_time"]
        self.accesstoken_duration_day = credentials["accesstoken_duration_day"]
        self.refreshtoken = credentials["refreshtoken"]
        self.refreshtoken_time = credentials["refreshtoken_time"]
        self.refreshtoken_duration_day = credentials["refreshtoken_duration_day"]
        self.client_id = credentials['client_id']
        self.username = credentials['username']
        self.password = credentials['password']
        self.authenticated = True

        return credentials["accesstoken"]

    # Load the credentials from the credentials file or generate new ones
    async def load_or_generate_creds(self, rec=False):
        await self.generate_creds()

    # Show the credentials
    def show_credentials(self):
        logging.info("show_credentials is not implemented")

    # Get requested information from the TV
    async def get_info(self, callback_message, subscribe_topic, publish_topic):
        logging.info("Getting information...")
        client = self.create_mqtt_client(client_id=self.client_id, certfile=certfile, keyfile=keyfile, username=self.username, password=self.accesstoken)
        logging.info(f"Adding callback to {callback_message}")
        client.message_callback_add(callback_message, self.on_info)

        client.connect_async(tv_ip, 36669, 60)
        client.loop_start()

        await self.wait_for_message(lambda: not client.connected_flag and not client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        logging.info(f"Subscribing for {subscribe_topic}")
        # client.subscribe(subscribe_topic)
        client.subscribe([
            (subscribe_topic, 0),
            (self.topicMobiBasepath + 'ui_service/data/authentication', 0), # if authentication fails, this will return a message
        ])

        logging.info(f"Publishing message to {publish_topic}")
        client.publish(publish_topic, None)

        await self.wait_for_message(lambda: self.info is None or client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return None

        if not self.authenticated:
            logging.info("NOT Authenticated")
            await self.generate_creds()

        client.loop_stop()
        client.disconnect()

        if self.info:
            logging.info(f"Information received: {self.info}")
            return json.loads(self.info)
        else:
            logging.error("Failed to get information")
            return None

    # Send a command to the TV
    async def send_command(self, publish_topic, command = None):
        logging.info("Sending command to TV...")
        client = self.create_mqtt_client(client_id=self.client_id, certfile=certfile, keyfile=keyfile, username=self.username, password=self.accesstoken)
        logging.info("No callback message needed for command sending.")

        client.connect_async(tv_ip, 36669, 60)
        client.loop_start()

        await self.wait_for_message(lambda: not client.connected_flag and not client.cancel_loop)
        if client.cancel_loop:
            logging.error("Failed to connect to MQTT broker. Exiting...")
            client.loop_stop()
            client.disconnect()
            return

        logging.info(f"Publishing {command} command to {publish_topic}")
        client.publish(publish_topic, command)
        
        logging.info("Command sent.")
        client.loop_stop()
        client.disconnect()

    # Get the current state of the TV
    async def get_tv_state(self):
        logging.info("Getting TV state...")
        get_tv_state_subscribe = self.topicBrcsBasepath + "ui_service/state"
        get_tv_state_callback = self.topicBrcsBasepath + "ui_service/state"
        get_tv_state_publish = self.topicTVUIBasepath + "actions/gettvstate"
        tv_state = await self.get_info(get_tv_state_callback, get_tv_state_subscribe, get_tv_state_publish)
        return tv_state

    # Get the source list of the TV
    async def get_source_list(self):
        logging.info("Getting source list...")
        get_source_list_callback = self.topicMobiBasepath + "ui_service/data/sourcelist"
        get_source_list_subscribe = self.topicMobiBasepath + "ui_service/data/sourcelist"
        get_source_list_publish = self.topicTVUIBasepath + "actions/sourcelist"
        source_list = await self.get_info(get_source_list_callback, get_source_list_subscribe, get_source_list_publish)
        return source_list
    
    # Get the volume of the TV
    async def get_volume(self):
        logging.info("Getting volume...")
        get_volume_callback = self.topicBrcsBasepath + "platform_service/actions/volumechange"
        get_volume_subscribe = self.topicBrcsBasepath + "platform_service/actions/volumechange"
        get_volume_publish = self.topicTVPSBasepath + "actions/getvolume"
        volume = await self.get_info(get_volume_callback, get_volume_subscribe, get_volume_publish)
        return volume

    # Get the app list of the TV
    async def get_app_list(self):
        logging.info("Getting app list...")
        get_app_list_callback = self.topicMobiBasepath + "ui_service/data/applist"
        get_app_list_subscribe = self.topicMobiBasepath + "ui_service/data/applist"
        get_app_list_publish = self.topicTVUIBasepath + "actions/applist"
        app_list = await self.get_info(get_app_list_callback, get_app_list_subscribe, get_app_list_publish)
        return app_list

    # Power Cycle the TV
    async def power_cycle_tv(self):
        logging.info("Power cycling the TV...")
        power_cycle_command = "KEY_POWER"
        power_cycle_publish = self.topicRemoBasepath + "actions/sendkey"
        await self.send_command(power_cycle_publish, power_cycle_command)
        return True

    # Send KEY to the TV
    async def send_key(self,key):
        logging.info("send key to TV..."+key)
        tv_state = await self.get_tv_state()
        if tv_state:
            if "statetype" in tv_state and tv_state["statetype"] == "fake_sleep_0":
                logging.info("TV is off. Not sending key...")
                return False
            else:
                send_key_publish = self.topicRemoBasepath + "actions/sendkey"
                await self.send_command(send_key_publish, key)
                return True
        else:
            logging.error("Failed to get TV state.")
            return False

    # Change the source of the TV
    async def change_source(self, source_id):
        logging.info(f"Changing source to {source_id}...")
        tv_state = await self.get_tv_state()
        if tv_state:
            if "statetype" in tv_state and tv_state["statetype"] == "fake_sleep_0":
                logging.info("TV is off. Not changing source...")
                return False
            else:
                logging.info("TV is on. Changing source...")
                change_source_publish = self.topicTVUIBasepath + "actions/changesource"
                change_source_command = json.dumps({"sourceid": source_id})
                await self.send_command(change_source_publish, change_source_command)
                return True
        else:
            logging.error("Failed to get TV state.")
            return False

    # Change the volume of the TV
    async def change_volume(self, volume):
        logging.info(f"Changing volume to {volume}...")
        tv_state = await self.get_tv_state()
        if tv_state:
            if "statetype" in tv_state and tv_state["statetype"] == "fake_sleep_0":
                logging.info("TV is off. Not changing volume...")
                return False
            else:
                change_volume_publish = self.topicTVPSBasepath + "actions/changevolume"
                change_volume_command = str(volume)
                await self.send_command(change_volume_publish, change_volume_command)
                return True
        else:
            logging.error("Failed to get TV state.")
            return False

    # Launch an app on the TV
    async def launch_app(self, app_name, app_list = None):
        logging.info(f"Launching app {app_name}...")

        app_id = None
        app_url = None

        if not app_list:
            app_list = await self.get_app_list()
            if not app_list:
                logging.error("Failed to get app list.")
                return False

        for app in app_list:
            if app["name"].upper() == app_name.upper():
                app_id = app["appId"]
                app_url = app["url"]
                app_name = app["name"]

        if app_id is None or app_url is None:
            logging.error("Failed to find app in app list.")
            return False

        tv_state = await self.get_tv_state()
        if tv_state:
            if "statetype" in tv_state and tv_state["statetype"] == "fake_sleep_0":
                logging.info("TV is off. Not launching app...")
                return False
            else:
                launch_app_publish = self.topicTVUIBasepath + "actions/launchapp"
                launch_app_command = json.dumps({"appId": app_id, "name": app_name, "url": app_url})
                await self.send_command(launch_app_publish, launch_app_command)
                return True
        else:
            logging.error("Failed to get TV state.")
            return False

async def run_main():
    auth = TVAuthenticator("192.168.178.25", "./rcm_certchain_pem.cer", "./rcm_pem_privkey.pkcs8")
    # await auth.load_or_generate_creds()
    client =await auth.request_auth_code()
    auth_code = input("Enter the four digits displayed on your TV: ")
    await auth.confirm_auth_code(auth_code, client)
    await auth.change_volume(13)
    # creds = {
    #     "client_id": auth.client_id,
    #     "username": auth.username,
    #     "password": auth.password,
    #     "accesstoken": auth.accesstoken,
    #     "accesstoken_time": auth.accesstoken_time,
    #     "accesstoken_duration_day": auth.accesstoken_duration_day,
    #     "refreshtoken": auth.refreshtoken,
    #     "refreshtoken_time": auth.refreshtoken_time,
    #     "refreshtoken_duration_day": auth.refreshtoken_duration_day
    # }
    # pprint(creds)
    # await auth.change_volume(10)
# Main function
if __name__ == "__main__":
    print("Initializing...")
    logging.info(f"Initializing")
    # Initialize the TVAuthenticator class
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_main())