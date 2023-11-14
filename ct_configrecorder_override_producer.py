# #
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify,merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#

import json
import boto3
import cfnresource
import os
import logging
import ast

def load_config():
    # Extract S3 bucket and key from the event
    bucket = 'smt-config-recorder'
    key = 'config/params-config-recorder.json'

    # Initialize the S3 client
    s3_client = boto3.client('s3')

    # Get the content of the S3 object
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response['Body'].read().decode('utf-8')

    # Print or use the content as needed
    print("Content of the S3 object:")
    print(content)

    return json.loads(content)

def lambda_handler(event, context):
    LOG_LEVEL = os.getenv('LOG_LEVEL')
    logging.getLogger().setLevel(LOG_LEVEL)
    try:
        logging.info('Event Data: ')
        logging.info(event)
        sqs_url = os.getenv('SQS_URL')
        excluded_accounts = os.getenv('EXCLUDED_ACCOUNTS')
        logging.info(f'Excluded Accounts: {excluded_accounts}')
        is_eb_trigerred = 'source' in event
        is_s3_trigerred = 'Records' in event
        
        logging.info(f'Is EventBridge Trigerred: {str(is_eb_trigerred)}')
        logging.info(f'Is S3 Trigerred: {str(is_s3_trigerred)}')
        event_source = ''
        
        if is_eb_trigerred and 's3' in event['Records'][0] and event['Records'][0]['s3']['object']['key'].endswith('params-config-recorder.json'):
            event_source = 'aws.controltower'
            logging.info(f"S3 Trigger Object name: {event['Records'][0]['s3']['object']['key']}")
            event_name = 'UpdateLandingZoneByS3Change'
        if is_eb_trigerred:
            event_source = event['source']
            logging.info(f'Control Tower Event Source: {event_source}')
            event_name = event['detail']['eventName']
            logging.info(f'Control Tower Event Name: {event_name}')
        
        if event_source == 'aws.controltower' and event_name == 'UpdateManagedAccount':    
            account = event['detail']['serviceEventDetails']['updateManagedAccountStatus']['account']['accountId']
            logging.info(f'overriding config recorder for SINGLE account: {account}')
            override_config_recorder(excluded_accounts, sqs_url, account, 'controltower')
        elif event_source == 'aws.controltower' and event_name == 'CreateManagedAccount':  
            account = event['detail']['serviceEventDetails']['createManagedAccountStatus']['account']['accountId']
            logging.info(f'overriding config recorder for SINGLE account: {account}')
            override_config_recorder(excluded_accounts, sqs_url, account, 'controltower')
        elif event_source == 'aws.controltower' and event_name == 'UpdateLandingZone':
            logging.info('overriding config recorder for ALL accounts due to UpdateLandingZone event')
            override_config_recorder(excluded_accounts, sqs_url, '', 'controltower')
        elif event_source == 'aws.controltower' and event_name == 'UpdateLandingZoneByS3Change':
            logging.info('overriding config recorder for ALL accounts due to S3 config update event')
            override_config_recorder(excluded_accounts, sqs_url, '', 'controltower')
        elif ('LogicalResourceId' in event) and (event['RequestType'] == 'Create'):
            logging.info('CREATE CREATE')
            logging.info(
                'overriding config recorder for ALL accounts because of first run after function deployment from CloudFormation')
            override_config_recorder(excluded_accounts, sqs_url, '', 'Create')
            response = {}
            ## Send signal back to CloudFormation after the first run
            cfnresource.send(event, context, cfnresource.SUCCESS, response, "CustomResourcePhysicalID")
        elif ('LogicalResourceId' in event) and (event['RequestType'] == 'Update'):
            logging.info('Update Update')
            logging.info(
                'overriding config recorder for ALL accounts because of first run after function deployment from CloudFormation')
            override_config_recorder(excluded_accounts, sqs_url, '', 'Update')
            response = {}
            update_excluded_accounts(excluded_accounts,sqs_url)
            
            ## Send signal back to CloudFormation after the first run
            cfnresource.send(event, context, cfnresource.SUCCESS, response, "CustomResourcePhysicalID")    
        elif ('LogicalResourceId' in event) and (event['RequestType'] == 'Delete'):
            logging.info('DELETE DELETE')
            logging.info(
                'overriding config recorder for ALL accounts because of first run after function deployment from CloudFormation')
            override_config_recorder(excluded_accounts, sqs_url, '', 'Delete')
            response = {}
            ## Send signal back to CloudFormation after the final run
            cfnresource.send(event, context, cfnresource.SUCCESS, response, "CustomResourcePhysicalID")
        else:
            logging.info("No matching event found")

        logging.info('Execution Successful')
        
        # TODO implement
        return {
            'statusCode': 200
        }

    except Exception as e:
        exception_type = e.__class__.__name__
        exception_message = str(e)
        logging.exception(f'{exception_type}: {exception_message}')

def get_excluded_resource_list(account, region):
    return "AWS::EC2::NetworkInterface,AWS::EC2::Volume"

def override_config_recorder(excluded_accounts, sqs_url, account, event):
    
    try:
        client = boto3.client('cloudformation')
        # Create a reusable Paginator
        paginator = client.get_paginator('list_stack_instances')
        
        # Create a PageIterator from the Paginator
        if account == '':
            page_iterator = paginator.paginate(StackSetName ='AWSControlTowerBP-BASELINE-CONFIG')
        else:
            page_iterator = paginator.paginate(StackSetName ='AWSControlTowerBP-BASELINE-CONFIG', StackInstanceAccount=account)
            
        sqs_client = boto3.client('sqs')
        for page in page_iterator:
            logging.info(page)
            
            for item in page['Summaries']:
                account = item['Account']
                region = item['Region']
                excluded_resource_list = get_excluded_resource_list(account, region)
                send_message_to_sqs(
                    event, 
                    account, 
                    region, 
                    excluded_accounts, 
                    excluded_resource_list, 
                    sqs_client, 
                    sqs_url
                    )
    
    except Exception as e:
        exception_type = e.__class__.__name__
        exception_message = str(e)
        logging.exception(f'{exception_type}: {exception_message}')

def send_message_to_sqs(event, account, region, excluded_accounts, config_recorder_excluded_resource_list, sqs_client, sqs_url):
    config = load_config()
    excluded_accounts = config['ExcludedAccounts']
    try:

        #Proceed only if the account is not excluded
        if account not in excluded_accounts:
        
            #construct sqs message
            sqs_msg = f'{{"Account": "{excluded_accounts}", "Region": "{region}", "Event": "{event}", "ConfigRecorderExcludedResourceList": "{config_recorder_excluded_resource_list}"}}'

            #send message to sqs
            response = sqs_client.send_message(
            QueueUrl=sqs_url,
            MessageBody=sqs_msg)
            logging.info(f'message sent to sqs: {sqs_msg}')
            
        else:    
            logging.info(f'Account excluded: {account}')
                
    except Exception as e:
        exception_type = e.__class__.__name__
        exception_message = str(e)
        logging.exception(f'{exception_type}: {exception_message}') 
                   
def update_excluded_accounts(excluded_accounts,sqs_url):
    
    try:
        acctid = boto3.client('sts')
        
        new_excluded_accounts = "['" + acctid.get_caller_identity().get('Account') + "']"
        
        logging.info(f'templist: {new_excluded_accounts}')
        
        templist=ast.literal_eval(excluded_accounts)
        
        templist_out=[]
        
        for acct in templist:
            
            if acctid.get_caller_identity().get('Account') != acct:
                templist_out.append(acct)
                logging.info(f'Delete request sent: {acct}')
                override_config_recorder(new_excluded_accounts, sqs_url, acct, 'Delete')
        
    except Exception as e:
        exception_type = e.__class__.__name__
        exception_message = str(e)
        logging.exception(f'{exception_type}: {exception_message}')
