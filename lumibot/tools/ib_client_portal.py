import logging
import subprocess
import os
import time
import requests
import webbrowser
import platform
import warnings
import psutil

class IBClientPortal:
    def __init__(self, config, script_dir=None):
        self.script_dir = script_dir or os.path.dirname(os.path.abspath(__file__))
        self.client_portal_dir = os.path.join(self.script_dir, 'ib_clientportal.gw')
        self.client_portal_script_name = 'run.bat' if platform.system() == 'Windows' else 'run.sh'
        self.client_portal_script = os.path.join(self.client_portal_dir, 'bin', self.client_portal_script_name)
        self.config_file = os.path.join(self.client_portal_dir, 'root', 'conf.yaml')
        self.base_url = 'https://localhost:3000'
        self.login_url = self.base_url

        self.status_check_endpoint = f'{self.base_url}/v1/portal/iserver/auth/status'
        self.account_list_endpoint = f'{self.base_url}/v1/portal/portfolio/accounts'
        self.account_info_endpoint = f'{self.base_url}/v1/portal/account/summary'
        
        self.check_interval = 0.5
        self.max_checks = 3600
        self.post_ready_delay = 2
        self.process = None
        self.account_id = config["ACCOUNT_ID"]
        self.ib_username = config["IB_USERNAME"]
        self.ib_password = config["IB_PASSWORD"]


    def validate_paths(self):
        return os.path.exists(self.client_portal_script) and os.path.exists(self.config_file)

    def is_client_portal_running(self):
        for proc in psutil.process_iter(['name', 'cmdline']):
            if self.client_portal_script_name in proc.info['name'] or \
               (proc.info['cmdline'] and self.client_portal_script_name in proc.info['cmdline'][0]):
                return proc
        return None

    def start_client_portal(self):
        if not self.validate_paths():
            logging.error("Client Portal paths are invalid.")
            return False

        running_process = self.is_client_portal_running()
        if running_process:
            logging.info(f"Client Portal is already running (PID: {running_process.pid})")
            return True

        relative_script = os.path.relpath(self.client_portal_script, self.client_portal_dir)
        relative_config = os.path.relpath(self.config_file, self.client_portal_dir)
        shell_command = (['cmd', '/c'] if platform.system() == 'Windows' else ['bash']) + [relative_script, relative_config]

        try:
            self.process = subprocess.Popen(
                shell_command,
                cwd=self.client_portal_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            self.process.poll()
            if self.process.returncode is None:
                logging.info("Interactive Brokers Client Portal process started.")
                return True
            else:
                raise Exception("A problem arised with the gateway process")
                
        except Exception as e:
            logging.error(f"Failed to start the Interactive Brokers Client Portal: {e}")
            return False

    def wait_for_client_portal_and_login(self):
        warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)
        for _ in range(self.max_checks):
            try:
                response = requests.get(self.status_check_endpoint, verify=False)
                if response.status_code == 200:
                    status_data = response.json()
                    if status_data.get('authenticated', False):
                        logging.info("Client Portal is ready and authenticated.")
                        return True
                    elif status_data.get('connected', False) and not status_data.get('authenticated', False):
                        webbrowser.open(self.login_url)
                        logging.info("Please log in through the opened browser window.")
                    else:
                        logging.info("A weird error has occurred")
                elif response.status_code == 401:
                    webbrowser.open(self.login_url)
                    logging.info("Please log in through the opened browser window.")
            except requests.exceptions.RequestException as e:
                if "Connection refused" not in str(e):
                    logging.error(f"Status check failed: {e}")
            time.sleep(self.check_interval)
        logging.error("Client Portal did not become ready and authenticated in time.")
        return False

    def get_contract_details_for_contract(self, contract):
        conid=contract.conId
        url = f"{self.base_url}/v1/iserver/contract/{conid}/info"
        response = self.get_json_from_endpoint(url, "getting account details")
        return response
    
    def get_account_info(self):
        try:
            logging.info("Attempting to retrieve account information.")
            response = requests.get(self.account_list_endpoint, verify=False)
            if response.status_code == 200:
                accounts_data = response.json()
                if accounts_data:
                    if not self.account_id:
                        self.account_id = accounts_data[0]['id']

                    response = requests.get(f"{self.account_info_endpoint}?accountId={self.account_id}", verify=False)
                    if response.status_code == 200:
                        return response.json()
                    elif response.status_code == 404:
                        logging.warning("Account information endpoint not found. Returning list of accounts.")
                        return {'accounts': accounts_data}
                    else:
                        logging.error(f"Failed to get detailed account info. Status code: {response.status_code}")
                else:
                    logging.warning("No accounts found in the response.")
            else:
                logging.error(f"Failed to list accounts. Status code: {response.status_code}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error getting account info: {e}")
            return None
        
    def get_account_balances(self):
        """
        Retrieves the account balances for a given account ID.
        """
        # Define the endpoint URL for fetching account balances
        url = f"{self.base_url}/v1/portal/portfolio/{self.account_id}/ledger"
        response = self.get_json_from_endpoint(url, "getting account balances")
        return response
        
    def get_json_from_endpoint(self, endpoint, description):
        """
        Retrieves the account balances for a given account ID.
        """
        try:
            # Make the request to the endpoint
            response = requests.get(endpoint, verify=False)

            # Check if the request was successful
            if response.status_code == 200:
                # Return the JSON response containing the account balances
                return response.json()
            else:
                # Log an error message if the request failed
                logging.error(f"Failed {description}. Status code: {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            # Log an error message if there was a problem with the request
            logging.error(f"Error {description}: {e}")
            return None
        
    def get_open_orders(self):
        # Define the endpoint URL for fetching account balances
        url = f'{self.base_url}/v1/iserver/account/orders?filters=accountId={self.account_id}'
        response = self.get_json_from_endpoint(url, "getting open orders")
        return response
    
    def get_positions(self):
        """
        Retrieves the current positions for a given account ID.
        """
        url = f"{self.base_url}/v1/portal/portfolio/{self.account_id}/positions"
        response = self.get_json_from_endpoint(url, "getting account positions")
        return response

    def run(self):
        if self.start_client_portal():
            time.sleep(3)
            if self.wait_for_client_portal_and_login():
                logging.info("hh")
                time.sleep(self.post_ready_delay)
                return self.get_account_info()
        return None

    def stop(self):
        if self.process:
            self.process.terminate()
            logging.info("Interactive Brokers Client Portal process terminated.")
        else:
            logging.info("No Client Portal process to terminate.")