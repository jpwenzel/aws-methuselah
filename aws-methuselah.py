# encoding=utf8
#!/usr/bin/python
#
# aws-methuselah.py
#
# List long running AWS instances.

import sys
reload(sys)
sys.setdefaultencoding('utf8')

from datetime import tzinfo, timedelta, datetime
import boto3
import pytz
import sys
from tabulate import tabulate
import math
import argparse
from jq import jq
import json

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# What's my age again? (in days) / use command line argument to override
defaultInstanceMaxAge = 3

# Threshold (in dollars) / use command line argument to override
defaultCostNotificationThreshold = defaultInstanceMaxAge * 5

defaultRegion = "all"

# Ignored instances
ignoredInstances = [
    'i-00000000',		# Add EC2 instance IDs that should be ignored here
]

ignoredTags = [
    'ignoreMeTag',         # Add instance tags that should be ignored here
]

ignoredStacks = [
    'ignore-stack-1',       # Add stacks that should be ignored here
]

priceList={}
with open('resources/ec2-prices.json') as json_data:
    d = json.load(json_data)
    priceList = jq("[ .[] | {(.instance_type): ( .pricing | to_entries | reduce .[] as $item ( {}; . + {($item.key): $item.value.linux.ondemand} ) ) } ] | add").transform(d)

def instancePriceInRegion(instanceSize, region):
    # Ignore region for now
    #return calculateInstancePrices().get(instanceSize)
    if priceList.get(instanceSize).get(region) is not None:
        return float(priceList.get(instanceSize).get(region))
    else:
        return None

# ----------------------------------------------------------------------------
# Parse command line arguments
# ----------------------------------------------------------------------------

parser = argparse.ArgumentParser()
parser.add_argument("--awsprofile", help="AWS profile to be used for checks")
parser.add_argument("--days", type=int,
                    help="Age of EC2 instances to check (in days); default=%d" % defaultInstanceMaxAge)
parser.add_argument("--costs", type=int, help="Cost threshold; default=%d" %
                    defaultCostNotificationThreshold)
parser.add_argument("--region", type=str, help="AWS Region; default=%s" %
                    defaultRegion)
args = parser.parse_args()

instanceMaxAge = args.days or defaultInstanceMaxAge
costNotificationThreshold = args.costs or defaultCostNotificationThreshold

# ----------------------------------------------------------------------------
# Timestamps
# ----------------------------------------------------------------------------
ZERO = timedelta(0)


class UTC(tzinfo):

    def utcoffset(self, dt):
        return ZERO

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return ZERO

utc = UTC()
now = datetime.now(utc)
past = now + timedelta(days=-instanceMaxAge)

costSum = 0
totalignoredInstances = 0
totalInstances = 0
resultTable = []

# ----------------------------------------------------------------------------
# Query AWS for EC2 instances
# ----------------------------------------------------------------------------
print "Looking for EC2 instances created > %d days ago..." % (instanceMaxAge)
print "Cost notification threshold set to $%d." % (costNotificationThreshold)

if not args.awsprofile:
    awsProfile = None
    session = boto3.session.Session()
else:
    awsProfile = args.awsprofile
    print "Using account %s" % awsProfile
    session = boto3.session.Session(profile_name="%s" % awsProfile)

if args.region:
    regions = [args.region]
else:
    regions = session.get_available_regions('ec2')

for region in regions:
    if awsProfile:
        ec2RegionalSession = boto3.session.Session(
            region_name=region, profile_name=awsProfile)
    else:
        ec2RegionalSession = boto3.session.Session(region_name=region)
    ec2 = ec2RegionalSession.resource('ec2')
    print "Checking region '%s'…" % region,

    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['pending', 'running']}])

    # Filter results, keep only matching instances (created before 'past')
    filteredInstances = [
        instance for instance in instances
        if instance.launch_time <= past]
    print "%d instance(s) found." % len(filteredInstances)
    totalInstances += len(filteredInstances)

    for instance in filteredInstances:
        if instance.id in ignoredInstances:
            totalignoredInstances += 1
            continue
        else:
            if len(instance.id) > 10:
                instanceId = instance.id[:8] + '..'
            else:
                instanceId = instance.id
            instanceName = "N/A"
            instanceType = instance.instance_type[:6]
            vpcName = "N/A"
            stackName = "N/A"
            vpcNoCleanup = 'N/A'

            # Determine VPC name
            vpcId = instance.vpc_id
            if vpcId is not None:
                vpc = ec2.Vpc(vpcId)
                if vpc.tags is not None:
                    vpcNameTag = [tag['Value']
                                  for tag in vpc.tags if tag['Key'] == 'Name']
                    if vpcNameTag:
                        vpcName = vpcNameTag[0] + ' (%s)' % vpcId
                    else:
                        vpcName = "(%s)" % vpcId
                    vpcNoCleanupTag = ['*'
                                       for tag in vpc.tags if tag['Key'] == 'no-cleanup']
                    if vpcNoCleanupTag:
                        vpcNoCleanup = vpcNoCleanupTag[0]

            # Determine instance name tag
            if instance.tags is not None:
                instanceNameTag = [tag['Value']
                                   for tag in instance.tags if tag['Key'] == 'Name']
                if not instanceNameTag:
                    instanceName = "N/A"
                else:
                    instanceName = instanceNameTag[0]
                # Determine stack name tag
                stackNameTag = [tag['Value']
                                for tag in instance.tags if tag['Key'] == 'aws:cloudformation:stack-name']
                if not stackNameTag:
                    stackName = "N/A"
                else:
                    stackName = stackNameTag[0]

            # Check if name contains ignored instance tag
            if any(tag in name for name in [instanceName, stackName] for tag in ignoredTags):
                totalignoredInstances += 1
                continue

            # Check if instance is part of a ignored stack
            if stackName in ignoredStacks:
                totalignoredInstances += 1
                continue

            # Determine run time
            runHours = math.ceil(
                (now - instance.launch_time).total_seconds() / 3600)

            # Determine price
            instancePrice = instancePriceInRegion(instance.instance_type, region)
            if instancePrice is not None:
                instanceCost = instancePrice * runHours
                costSum += instanceCost
                costStr = "$%5.2f" % instanceCost
            else:
                costStr = None

            # Sanitize instance, stack, and VPC names
            instanceName.encode('ascii', 'ignore')
            stackName.encode('ascii', 'ignore')
            vpcName.encode('ascii', 'ignore')

            resultTable.append([instanceId, instanceName, stackName, vpcName, region,
                                instanceType, instance.launch_time.strftime('%Y-%m-%d'), vpcNoCleanup, costStr])

# ----------------------------------------------------------------------------
# Output results
# ----------------------------------------------------------------------------
if (len(resultTable) > 0):
    print ""
    print tabulate(resultTable, headers=["ID", "Instance Name", "Stack Name", "VPC Name/ID", "Region", "Size", "Created on", "no-del", "Costs"])
    print ""
    print "%d running instances found (of which %d are ignored)." % (totalInstances, totalignoredInstances)
    print "(Estimated) running costs since creation: $%.2f. " % costSum

    if (costSum > costNotificationThreshold):
        sys.exit(1)
    else:
        print "Costs are below notification threshold ($%d)." % (costNotificationThreshold)
        sys.exit(0)
else:
    print "All clear (none found; %d running instances were ignored)." % totalignoredInstances
    sys.exit(0)
