import robin_stocks.robinhood as rh   
import boto3


def get_parameter_value(parameter_name):
    ssm = boto3.client('ssm')
    response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    return response['Parameter']['Value']

login_rh = rh.authentication.login(username=get_parameter_value("/robinhood/username"), password=get_parameter_value("/robinhood/password"))

print(login_rh)