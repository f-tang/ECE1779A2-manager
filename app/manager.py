from flask import render_template, redirect, url_for, request,g, session
from app import webapp, config, get_db, teardown_db, db_config
import boto3
import pymysql

from datetime import datetime, timedelta
from operator import itemgetter
import re
import subprocess


BUCKET_NAME = 'ece1779-ft'
BALANCER_NAME = 'ece1779balancer'


# access aws s3 bucket
def get_s3bucket():
    aws_session = boto3.Session(profile_name="ta")
    s3 = aws_session.resource('s3')

    return s3.Bucket(BUCKET_NAME)

# access aws s3 client
def get_s3client():
    aws_session = boto3.Session(profile_name="ta")
    s3 = aws_session.client('s3')

    return s3

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


@webapp.route('/', methods=['GET'])
@webapp.route('/manager',methods=['GET'])
# Display an HTML list of all ec2 instances
def ec2_list():

    ec2 = get_ec2resource()

    #    instances = ec2.instances.filter(
    #        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])

    instances = ec2.instances.filter(
        Filters=[{'Name':'tag:type', 'Values':['ece1779worker']}])

    return render_template("list.html", title="Worker List", instances=instances)



@webapp.route('/manager/<id>',methods=['GET'])
#Display details about a specific instance.
def ec2_view(id):
    ec2 = get_ec2resource()
    instance = ec2.Instance(id)

    client = get_CWclient()

    metric_name = 'CPUUtilization'

    ##    CPUUtilization, NetworkIn, NetworkOut, NetworkPacketsIn,
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
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    cpu_stats = []

    for point in cpu['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute / 60
        cpu_stats.append([time, point['Average']])

    cpu_stats = sorted(cpu_stats, key=itemgetter(0))

    statistic = 'Sum'  # could be Sum,Maximum,Minimum,SampleCount,Average

    network_in = client.get_metric_statistics(
        Period=1 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName='NetworkIn',
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    net_in_stats = []

    for point in network_in['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute / 60
        net_in_stats.append([time, point['Sum']])

    net_in_stats = sorted(net_in_stats, key=itemgetter(0))

    network_out = client.get_metric_statistics(
        Period=5 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName='NetworkOut',
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    net_out_stats = []

    for point in network_out['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute / 60
        net_out_stats.append([time, point['Sum']])

        net_out_stats = sorted(net_out_stats, key=itemgetter(0))

    return render_template("view.html", title="Instance Info",
                           instance=instance,
                           cpu_stats=cpu_stats,
                           net_in_stats=net_in_stats,
                           net_out_stats=net_out_stats)


@webapp.route('/manager/create',methods=['POST'])
# Start a new EC2 instance
def ec2_create():
    ec2 = get_ec2resource()
    instances = ec2.create_instances(ImageId=config.ami_id,
                         InstanceType='t2.small',
                         MinCount=1,
                         MaxCount=1,
                         SecurityGroupIds=config.sg_ids,
                         TagSpecifications=[{
                             'ResourceType':'instance',
                             'Tags':[{'Key':'type', 'Value':'ece1779worker'}]
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

    return redirect(url_for('ec2_list'))


@webapp.route('/manager/delete/<id>',methods=['POST'])
# Terminate a EC2 instance
def ec2_destroy(id):
    # create connection to ec2
    ec2 = get_ec2resource()

    ec2.instances.filter(InstanceIds=[id]).terminate()

    return redirect(url_for('ec2_list'))



