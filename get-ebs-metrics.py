#!/usr/bin/env python
# purpose: to pull and calculate throughput and IO statistics for a set of EBS volumes; data source source is cloudwatch
# usage: python get-ebs-metrics.py

import argparse
import boto3
from botocore.config import Config
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time
from random import randrange
import sys

# parse command-line arguments for input instance file, output file, and days back to pull metrics 
# csv must have columns: type,region,instance
def parse_args():
    parser = argparse.ArgumentParser(description='instance check script')
    parser.add_argument('-i', '--input_file', help='input_file', type=str, required=False)
    parser.add_argument('-o', '--ouput_file', help='ouput_file', type=str, required=False)
    parser.add_argument('-d', '--days_back', help='days_back', type=int, required=False)
    parser.set_defaults(input_file='data/ebs-input.csv', output_file='data/ebs-cw-output.csv', days_back=30)
    args = parser.parse_args()
    return args

def cw_pull_metric(cw_client, df, metric_name, namespace, ebs_id, stat, unit, period, days_back):
    cw_response = cw_client.get_metric_data(
        MetricDataQueries=[
            {
                'Id': 'string1',
                'MetricStat': {
                    'Metric': {
                        'Namespace': namespace,
                        'MetricName': metric_name,
                        'Dimensions': [
                            {
                                'Name': 'VolumeId',
                                'Value': ebs_id
                            },
                        ]
                    },
                    'Period': period,
                    'Stat': stat,
                    'Unit': unit
                },
                'ReturnData': True
            }
        ],
        StartTime=datetime.utcnow() - timedelta(days=days_back),
        EndTime=datetime.utcnow()
    )
    df[metric_name] = cw_response['MetricDataResults'][0]['Values']
    return df

# check for dividing by zero and return 0 versus NaN
def divide_numbers(x,y):
    np.seterr(invalid='ignore')
    try:
        val = x / y
        if np.isnan(val):
            return 0
        else:
            return val
    except:
        return 0
    
# to determine the average 
def calc_avg_iop(row_dict):
    # divide monthly throughput by monthly IOPS per month 
    row_dict['VolumeOpsSum'] = row_dict['VolumeReadOpsSum'] + row_dict['VolumeWriteOpsSum'] 
    row_dict['VolumeBytesSum'] = row_dict['VolumeReadBytesSum'] + row_dict['VolumeWriteBytesSum'] 
    row_dict['IoSize'] = divide_numbers(row_dict['VolumeBytesSum'], row_dict['VolumeOpsSum'])
    return row_dict

def get_ebs_tag_value(key, vol_info):
    try:
        tag_name = ''
        if 'Tags' in vol_info['Volumes'][0]:
            tags = vol_info['Volumes'][0]['Tags']
            for entry in tags:
                if key in entry.values():
                    tag_name = entry['Value']
        else:
            tag_name = ''
        return tag_name
    except Exception as e: 
        print(f'An error occurred searching for EBS tag')
        print(e)
        return ''

def get_ec2_tag_value(key, ec2_instance_id):
    try:
        ec2 = boto3.resource('ec2')
        ec2instance = ec2.Instance(ec2_instance_id)
        ec2_instance_name = ''
        for tags in ec2instance.tags:
            if tags["Key"] == 'Name':
                ec2_instance_name = tags["Value"]
        return ec2_instance_name
    except Exception as e: 
        print(f'An error occurred during making call for Ec2 instance id: {ec2_instance_id}')
        print(e)
        return 'NaN'

def get_ebs_param(param, vol_info, default=''):
    try:
        param_value = ''
        if param in vol_info['Volumes'][0]:
            param_value = vol_info['Volumes'][0][param]
        else:
            param_value = default
        return param_value
    except Exception as e: 
        print(f'An error occurred searching for EBS parameter')
        print(e)
        return default

def get_vol_info(args, vol_df):
    
    ebs_info_df = pd.DataFrame()
    
    # boto3 client config
    config = Config(
        retries = dict(
            max_attempts = 10
        )
    )
        
    for row in vol_df.itertuples():
        try:
            row_dict = {}

            ec2_client = boto3.client('ec2', region_name=row.region, config=config)
            vol_info = ec2_client.describe_volumes(VolumeIds=[row.ebs_id])
            row_dict['ebs_id'] = row.ebs_id
            row_dict['ebs_name'] = get_ebs_tag_value('Name', vol_info)
            row_dict['ebs_device'] = vol_info['Volumes'][0]['Attachments'][0]['Device']
            row_dict['ec2_instance_id'] = vol_info['Volumes'][0]['Attachments'][0]['InstanceId']
            row_dict['ec2_instance_name'] = get_ec2_tag_value('Name', row_dict['ec2_instance_id'])
            row_dict['region'] = row.region
            row_dict['az'] = vol_info['Volumes'][0]['AvailabilityZone']
            row_dict['ebs_type'] = vol_info['Volumes'][0]['VolumeType']
            row_dict['ebs_size'] = vol_info['Volumes'][0]['Size']
            row_dict['ebs_iops'] = get_ebs_param('Iops', vol_info)
            row_dict['ebs_throughput'] = get_ebs_param('Throughput', vol_info)

        except Exception as e: 
            print(f'An error occurred during making call for EBS id: {row.ebs_id}')
            print(e)
            #pass

        df_temp = pd.DataFrame(row_dict, index=[0])

        nl = '\n'
        pd.set_option('display.width', 200)
        pd.set_option('display.colheader_justify', 'center')
        print(f'Found info for EBS volume:{nl} {df_temp}')
        ebs_info_df = pd.concat([ebs_info_df, df_temp])
    return ebs_info_df 


def get_ebs_data(args, ebs_info_df):

    output_df = pd.DataFrame()

    # ebs metrics of interest
    ebs_metrics = {
        'VolumeReadOps': 'Count',
        'VolumeWriteOps': 'Count',
        'VolumeReadBytes': 'Bytes',
        'VolumeWriteBytes': 'Bytes'
    }

    # stats of interest 
    ebs_stat = ['Maximum', 'Sum']
    
    # days back period to poll cloudwatch 
    days_back = args.days_back
    month_span = days_back/30
    
    # increasing attempts in case of rate limiting 
    config = Config(
        retries = dict(
            max_attempts = 10
        )
    )

    # pandas group by per region, then iterate though each regions EBS volumes 
    region_df = ebs_info_df.groupby('region')
    for region, ebs_id in region_df:
        cw_client = boto3.client('cloudwatch', region_name=region, config=config)
        for row in ebs_id.itertuples():
            row_dict = {}
            for stat in ebs_stat:
                for metric_name, unit in ebs_metrics.items():
                    try:
                        time.sleep(2)
                        df = pd.DataFrame()
                        # maximum statistic is only supported on Nitro-based instances
                        df = cw_pull_metric(cw_client, df, metric_name, 'AWS/EBS', row.ebs_id, stat, unit, 300, days_back)
                        # divide by 60 seconds 1 hertz data for a 60 second period 
                        if stat == 'Maximum':
                            df_max = df.div(60)
                            df_max = df_max.round(1)
                            max_value = df_max[metric_name].max()
                            row_dict[metric_name + 'Maximum'] = max_value
                        # only get Sum for throughtput stats
                        if stat == 'Sum' and (metric_name == 'VolumeReadBytes' or 'VolumeWriteBytes' or 'VolumeReadOps' or 'VolumeWriteOps'):
                            row_dict[metric_name + 'Sum'] = (df[metric_name].sum()/month_span)
                        
                        # can decide to remove any column but at least keep region and volumn_id
                        row_dict['ec2_instance_id'] = row.ec2_instance_id
                        row_dict['ec2_instance_name'] = row.ec2_instance_name
                        row_dict['ebs_type'] = row.ebs_type
                        row_dict['ebs_name'] = row.ebs_name
                        row_dict['ebs_id'] = row.ebs_id
                        row_dict['ebs_device'] = row.ebs_device
                        row_dict['region'] = row.region
                        row_dict['ebs_size'] = row.ebs_size
                        row_dict['ebs_throughput'] = row.ebs_throughput
                        row_dict['ebs_iops'] = row.ebs_iops

                    except Exception as e: 
                        print(f'An error occurred during making call for EBS id: {row.ebs_id}, metric: {metric_name}')
                        print(e)
                        pass
            # calc IO average size - read and write combined
            row_dict = calc_avg_iop(row_dict)
            # round off decimal values  
            df_temp = pd.DataFrame(row_dict, index=[0]).round(0)
            print(f'Query result: {df_temp}')
            output_df = pd.concat([output_df, df_temp])
    # get dataframe column list for ordering csv columns 
    col_list = list(output_df.columns)
    output_df.to_csv(args.output_file, index=False, columns=(sorted(col_list, reverse=True)))

def main():
    args = parse_args()

    vol_df = pd.read_csv(args.input_file)
    # get volume and associated Ec2 instance information
    ebs_info_df = get_vol_info(args, vol_df)
    # pull Cloudwatch data for volumes and output to csv
    get_ebs_data(args, ebs_info_df)
    
if __name__ == "__main__":
    main()