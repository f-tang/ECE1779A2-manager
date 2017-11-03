from flask import g
import pymysql.cursors
import boto3
import random
from operator import itemgetter
import numpy as np

from botocore.client import Config

ami_id = "ami-26248a5c"
sg_ids = ["sg-85770ff7", "sg-04b99e76"]


# access database
def connect_to_database():
    return pymysql.connect(host='127.0.0.1',
                           user='ece1779',
                           password='secret',
                           db='ece1779')


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._databse = connect_to_database()
    return db


# database exception teardown
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


# access aws ec2 resource
def get_ec2resource():
    aws_session = boto3.Session(profile_name="ta", region_name="us-east-1")
    ec2 = aws_session.resource('ec2')
    return ec2


# access aws cloud watch client
def get_CWclient():
    aws_session = boto3.Session(profile_name="ta", region_name="us-east-1")
    cw = aws_session.client('cloudwatch')
    return cw


# access aws ELB client
def get_ELBclient():
    aws_session = boto3.Session(profile_name="ta", region_name="us-east-1")
    elb = aws_session.client('elb')
    return elb


# create ec2 instances
def ec2_create(num_create):
    ec2 = get_ec2resource()
    instances = ec2.create_instances(ImageId=ami_id,
                                     InstanceType='t2.small',
                                     MinCount=1,
                                     MaxCount=num_create,
                                     SecurityGroupIds=sg_ids,
                                     TagSpecifications=[{
                                         'ResourceType': 'instance',
                                         'Tags': [{'Key': 'type', 'Value': 'ece1779worker'}]
                                     }]
                                     )

    elb = get_ELBclient()
    for instance in instances:
        elb.register_instances_with_load_balancer(
            LoadBalancerName='ece1779balancer',
            Instances=[
                {
                    'InstanceId': instance.id
                },
            ])
    return 0

# TODO: delete ec2 instances
def ec2_delete(num_delete):
    ec2 = get_ec2resource()
    workers = list(ec2.instances.filter(
        Filters= [{'Key': 'type', 'Value': 'ece1779worker'},
                  {'Key': 'instance-state-name', 'Values': ['running', 'pending']}]))

    random.shuffle(workers)
    for i in range(num_delete):
            workers[i].terminate()
    return 0

# TODO: get EC2 average CPU utilization
def get_utl():
    ec2 = get_ec2resource()
    instances = ec2.instances.filter(
        Filters= [{'Key': 'type', 'Value': 'ece1779worker'},
                  {'Key': 'instance-state-name', 'Values': ['running', 'pending']}])

    cpu_list = []

    for ins in instances:
        cpu_status = get_cpu_stats(ins.id)
        if len(cpu_status) > 0:
            cpu = cpu_status[-1][1]
            cpu_list.append(cpu)

    average_utl = np.mean(cpu_list)

    return average_utl

def get_cpu_stats(instance_id):
    client = boto3.client('cloudwatch')

    metric_name = 'CPUUtilization'

    #    CPUUtilization, NetworkIn, NetworkOut, NetworkPacketsIn,
    #    NetworkPacketsOut, DiskWriteBytes, DiskReadBytes, DiskWriteOps,
    #    DiskReadOps, CPUCreditBalance, CPUCreditUsage, StatusCheckFailed,
    #    StatusCheckFailed_Instance, StatusCheckFailed_System

    namespace = 'AWS/EC2'
    statistic = 'Average'  # could be Sum,Maximum,Minimum,SampleCount,Average

    cpu = client.get_metric_statistics(
        Period=1 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName=metric_name,
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}]
    )

    cpu_stats = []

    for point in cpu['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute / 60
        cpu_stats.append([time, point['Average']])

    return sorted(cpu_stats, key=itemgetter(0))


# TODO: get number of EC2 worker instances
def get_worker_num():
    ec2 = get_ec2resource()
    instances = ec2.instances.filter(
        Filters=[{'Key': 'type', 'Value': 'ece1779worker'},
                 {'Key': 'instance-state-name', 'Values': ['running', 'pending']}])
    num_worker = len(instances)

    return num_worker


def main():
    MAX_POOL = 10
    try:
        num_worker = get_worker_num()
        if num_worker < 1:
            # no worker, create one
            ec2_create(1)
            return 0
        if num_worker > MAX_POOL:
            # full worker pool, do nothing
            return 0

        cnx = get_db()
        cursor = cnx.cursor()
        cursor.execute("SELECT * FROM policy")
        policy = cursor.fetchone()

        if policy is None:
            # cannot get policy, return error
            print("database is broken")
            cursor.close()
            cnx.close()
            return 1

        scaling_status = int(policy[5])
        if scaling_status == 0:
            # auto-scaling is off, do nothing
            print("auto-scaling is off, you can switch on in manager UI")
            return 0

        grow_threshold = int(policy[1]) / 100
        shrink_threshold = int(policy[2]) / 100
        grow_ratio = int(policy[3])
        shrink_ratio = int(policy[4])

        cpu_utl = get_utl() # TODO: make sure cpu_utl is a float(0~1)

        if cpu_utl < grow_threshold:
            num_create = min([num_worker * grow_ratio, MAX_POOL-num_worker])
            ec2_create(num_create)
        elif cpu_utl > shrink_threshold:
            num_delete = min([num_worker - num_worker // shrink_ratio, num_worker - 1])
            ec2_delete(num_delete)

        return 0

    except Exception as e:
        teardown_db(e)
        print(str(e))


if __name__ == '__main__':
    main()
