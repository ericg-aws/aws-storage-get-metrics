#!/usr/bin/env python
# purpose: to pull cloudwatch statistics for a set of RDS instances and Ec2 EBS IDs, using a csv for inputs
import argparse
import boto3
from botocore.config import Config
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time
from random import randrange


# parse command-line arguments for region and input file
# csv must have columns: type,region,instance
def parse_args():
    parser = argparse.ArgumentParser(description='instance check script')
    parser.add_argument('-i', '--input_file', help='input_file', type=str, required=False)
    parser.add_argument('-o', '--ouput_file', help='ouput_file', type=str, required=False)
    parser.add_argument('-d', '--days_back', help='days_back', type=int, required=False)
    parser.set_defaults(input_file='data/input.csv', output_file='data/output.csv', days_back=30)
    args = parser.parse_args()
    return args

def cw_rds_pull_metric(cw_client, df, metric_name, namespace, instance_name, instance, stat, period, days_back):
    id_name = f'rdsmetricpull{randrange(1000000)}'
    start = ((datetime.utcnow().replace(microsecond=0, second=0, minute=0) - timedelta(hours=1)) - timedelta(days=days_back))
    end = (datetime.utcnow().replace(microsecond=0, second=0, minute=0) - timedelta(hours=1))

    print(metric_name, namespace, instance_name, instance, stat, period, days_back)
    cw_response = cw_client.get_metric_data(
        MetricDataQueries=[
            {
                'Id': id_name,
                'MetricStat': {
                    'Metric': {
                        'Namespace': namespace,
                        'MetricName': metric_name,
                        'Dimensions': [
                            {
                                'Name': instance_name,
                                'Value': instance
                            },
                        ]
                    },
                    'Period': period,
                    'Stat': stat,
                },
                'ReturnData': True
            }
        ],
        StartTime=start,
        EndTime=end,
        ScanBy='TimestampDescending'
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
    row_dict['VolumeIOPSSum'] = row_dict['ReadIOPSSum'] + row_dict['WriteIOPSSum'] 
    row_dict['VolumeBytesSum'] = row_dict['WriteThroughputSum'] + row_dict['ReadThroughputSum'] 
    row_dict['IoSize'] = divide_numbers(row_dict['VolumeBytesSum'], row_dict['VolumeIOPSSum'])
    return row_dict


def get_rds(args, instance_df):
    
    output_df = pd.DataFrame()
    
    # rds metrics of interest
    instance_metrics = {
        'ReadIOPS': 'Count',
        'WriteIOPS': 'Count',
        'WriteThroughput': 'Bytes',
        'ReadThroughput': 'Bytes'
    }

    # stats of interest 
    storage_stats = ['Maximum', 'Sum']
    
    # days back period to poll cloudwatch 
    days_back = args.days_back
    month_span = days_back/30
    
    # boto3 client config
    config = Config(
        retries = dict(
            max_attempts = 10
        )
    )
        
    for row in instance_df.itertuples():
        cw_client = boto3.client('cloudwatch', region_name=row.region, config=config)
        row_dict = {}
        for stat in storage_stats:
            for metric_name, unit in instance_metrics.items():
                try:
                    time.sleep(0)
                    df = pd.DataFrame()
                    # maximum statistic is only supported on Nitro-based and RDS instances 
                    # adjust period in seconds based upon the days back
                    df = cw_rds_pull_metric(cw_client, df, metric_name, 'AWS/RDS', 'DBInstanceIdentifier', row.instance, stat, 300, days_back)
                    # divide by 60 seconds 1 hertz data for a 60 second period 
                    if stat == 'Maximum':
                        df_max = df.div(60)
                        df_max = df_max.round(1)
                        max_value = df_max[metric_name].max()
                        row_dict[metric_name + 'Maximum'] = max_value
                    # only get Sum for all metrics pulled
                    if stat == 'Sum' and (metric_name == 'ReadIOPS' or 'WriteIOPS' or 'WriteThroughput' or 'ReadThroughput'):
                        row_dict[metric_name + 'Sum'] = (df[metric_name].sum()/month_span)
                    
                    # can decide to remove any column but at least keep region and volumn_id
                    row_dict['type'] = row.type
                    row_dict['region'] = row.region
                    row_dict['instance'] = row.instance
                except Exception as e: 
                    print(f'An error occurred during making call for id: {row.instance}, metric: {metric_name}')
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

    instance_df = pd.read_csv(args.input_file)
    get_rds(args, instance_df)
    
if __name__ == "__main__":
    main()