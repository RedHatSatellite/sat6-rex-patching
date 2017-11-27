#!/usr/bin/python

import json
import sys
import time
from optparse import OptionParser
from argparse import ArgumentParser
from datetime import datetime, timedelta
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# To setup hosts for remote execution:
# curl https://sat6.example.com:9090/ssh/pubkey >> ~/.ssh/authorized_keys

# Satellite parameters
url = "https://localhost/"
api = url + "api/"
katello_api = url + "katello/api/"
post_headers = {'content-type': 'application/json'}
ssl_verify = False

errata_job_name = "Install Errata - Katello SSH Default"
power_job_name = "Power Action - SSH Default"
command_job_name = "Run Command - SSH Default"

parser = ArgumentParser(description="Script to schedule remote execution jobs for installing available errata and reboot after updates that require reboot.")
parser.add_argument("-u", "--username", dest="username", required=True, help="Username to authenticate to Satellite API")
parser.add_argument("-p", "--password", dest="password", required=True, help="Password to authenticate to Satellite API")
parser.add_argument("-o", "--organization", dest="organization", required=True, help="Organization name in Satellite")
parser.add_argument("-c", "--host-collection", dest="host_collection", required=True, help="Name of a Host Collection containing the hosts you want to patch")
parser.add_argument("-t", "--apply-time", dest="apply_time", required=True, help="The time that you want to schedule the patching for in the following format: 2017-11-11 11:11:11")
parser.add_argument("-r", "--reboot-time", dest="reboot_time", required=True, help="The time that you want to schedule reboots for the hosts that require it, format: 2017-11-11 12:12:12")
parser.add_argument("-a", "--apply", action="store_true", default=False, dest="do_apply", help="Actually schedule the jobs (otherwise the script will run in no-op)")
args = parser.parse_args()


def get_json(location):
    """
    Performs a GET using the passed url location
    """
    try:
        result = requests.get(location, 
                            auth=(args.username, args.password), 
                            verify=ssl_verify)

    except requests.ConnectionError, e:
        print "Couldn't connect to the API, check connection or url"
        print e
        sys.exit(1)
    return result.json()

def get_with_json(location, json_data):
    """
    Performs a GET and passes the data to the url location
    """
    try:
        result = requests.get(location,
                            data=json_data,
                            auth=(args.username, args.password),
                            verify=ssl_verify,
                            headers=post_headers)

    except requests.ConnectionError, e:
        print "Couldn't connect to the API, check connection or url"
        print e
        sys.exit(1)
    return result.json()


def post_json(location, json_data):
    """
    Performs a POST and passes the data to the url location
    """
    try:
        result = requests.post(location,
                            data=json_data,
                            auth=(args.username, args.password),
                            verify=ssl_verify,
                            headers=post_headers)

    except requests.ConnectionError, e:
        print "Couldn't connect to the API, check connection or url"
        print e
        sys.exit(1)
    return result.json()

def put_json(location, json_data):
    """
    Performs a PUT and passes the data to the url location
    """

    result = requests.put(location,
                            data=json_data,
                            auth=(args.username, args.password),
                            verify=ssl_verify,
                            headers=post_headers)

    return result.json()

def pretty_json(json_data):
    
    return json.dumps(json_data, sort_keys=True, indent=4, separators=(',', ': '))

def main():

    # Get organzation ID
    orgs = get_json(katello_api + "organizations/")
    for org in orgs['results']:
        if org['name'] == args.organization:
           org_id = org['id']

    try:
        org_id
    except NameError:
        print "Organization " + args.organization + " does not exist. Exiting..." 
        exit(1)

    # Get all job templates
    job_templates_json = get_with_json(api + "job_templates", json.dumps({"per_page": "10000"}))["results"]
   
    # Get IDs of job templates 
    for job_template in job_templates_json:
        if job_template["name"] == errata_job_name:
            errata_job_id = job_template["id"]

        if job_template["name"] == power_job_name:
            power_job_id = job_template["id"]

        if job_template["name"] == command_job_name:
            command_job_id = job_template["id"]


    # Check if all job templates are found, exit otherwise
    if not 'errata_job_id' in locals():
        print errata_job_name + " job template not found. Exiting..."
        sys.exit(1)

    if not 'power_job_id' in locals():
        print power_job_name + " job template not found. Exiting..."
        sys.exit(1)

    if not 'command_job_id' in locals():
        print command_job_name + " job template not found. Exiting..."
        sys.exit(1)


    # TODO: this currently works for host_collections. make it work with lifecycle environments, host groups etc. 
    # note that hosts in a host collection called "Locked" will be excluded. useful if there are certain hosts that you don't want to patch, but still have in the same host collection.
    hosts_json = get_with_json(api + "hosts", json.dumps({"search": "host_collection = \"" + args.host_collection + "\" and !(host_collection = Locked)", "per_age": "10000"}))["results"]

    for host in hosts_json:
        # Get all erratas for this host
        erratas = get_with_json(api + "hosts/" + str(host["id"]) + "/errata", json.dumps({"per_page": "10000"}))["results"]
        
        errata_ids = []
        reboot_suggested = False
        
        # Put errata IDs in list and determine if this host will need reboot or not
        for errata in erratas:
            errata_ids.append(errata["errata_id"])
            if errata["reboot_suggested"]:
                reboot_suggested = True
       
        # If there are any erratas, schedule a job to install them
        if errata_ids:
            print host["name"] + ": Schedule errata install at " + args.apply_time + " for erratas: " + str(errata_ids)
            job_json = json.dumps({
                "job_invocation": {
                    "job_template_id": str(errata_job_id),  
                    "targeting_type": "dynamic_query",
                    "search_query": "name = " + host["name"],
                    "inputs": {
                        "errata": ",".join(errata_ids)
                    },
                    "scheduling": {
                        "start_at": args.apply_time
                    }
                }
            })
            if args.do_apply:
                post_json(api + "job_invocations", job_json) 
        
        else:
            print host["name"] + ": No erratas available"


        # If host needs reboot, schedule reboot job
        if reboot_suggested:
            print host["name"] + ": Schedule reboot at " + args.reboot_time
            job_json = json.dumps({
                "job_invocation": {
                    "job_template_id": str(power_job_id),
                    "targeting_type": "dynamic_query",
                    "search_query": "name = " + host["name"],
                    "inputs": {
                        "action": "restart"
                    },
                    "scheduling": {
                        "start_at": args.reboot_time
                    }
                }
            })
            if args.do_apply:
                post_json(api + "job_invocations", job_json)
          
if __name__ == "__main__":
    main()

