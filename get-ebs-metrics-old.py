#!/usr/bin/env python
# purpose: to pull cloudwatch statistics for a set of EBS IDs, using an Excel spreadsheet as input 
import argparse
import boto3
from botocore.config import Config
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time

# parse command-line arguments for region and input file
# xlsx file must have columns: instance_id, instance_name, instance_type, volume_type, volume_name, volume_id, volume_considered
# days of metrics history to consider 
def parse_args():
    parser = argparse.ArgumentParser(description='instance check script')
    parser.add_argument('-i', '--input_file', help='input_file', type=str, required=False)
    parser.add_argument('-o', '--ouput_file', help='ouput_file', type=str, required=False)
    parser.add_argument('-d', '--days_back', help='days_back', type=int, required=False)
    parser.set_defaults(input_file='data/input_ebs_volumes.xlsx', output_file='data/ebs-cw-output.csv', days_back=30)
    args = parser.parse_args()
    return args

# poll CloudWatch for EBS metrics
def cw_pull_metric(cw_client, df, metric_name, namespace, vol_id, stat, unit, period, days_back):
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
                                'Value': vol_id
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

def main():
    args = parse_args()

    output_df = pd.DataFrame()
    instance_df = pd.read_excel(args.input_file, sheet_name=1)
    # remove volumes that do not have a 1 in the considered column 
    instance_df = instance_df[instance_df.volume_considered != 0]
    
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
    
    # pandas group by per region, then iterate though each regions EBS volumes 
    region_df = instance_df.groupby("region")
    for region, instance in region_df:
        # increasing attempts in case of rate limiting 
        config = Config(
            retries = dict(
                max_attempts = 10
            )
        )
        cw_client = boto3.client('cloudwatch', region_name=region, config=config)
        for row in instance.itertuples():
            row_dict = {}
            for stat in ebs_stat:
                for metric_name, unit in ebs_metrics.items():
                    try:
                        time.sleep(2)
                        df = pd.DataFrame()
                        # maximum statistic is only supported on Nitro-based instances
                        df = cw_pull_metric(cw_client, df, metric_name, 'AWS/EBS', row.volume_id, stat, unit, 300, days_back)
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
                        row_dict['instance_id'] = row.instance_id
                        row_dict['instance_name'] = row.instance_name
                        row_dict['instance_type'] = row.instance_type
                        row_dict['volume_type'] = row.volume_type
                        row_dict['volume_name'] = row.volume_name
                        row_dict['volume_id'] = row.volume_id
                        row_dict['region'] = row.region
                    except Exception as e: 
                        print(f'An error occurred during making call for EBS id: {row.volume_id}, metric: {metric_name}')
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
    
if __name__ == "__main__":
    main()