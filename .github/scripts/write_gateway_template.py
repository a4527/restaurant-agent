import sys, json

gateway_id = sys.argv[1] if len(sys.argv) > 1 else ''

template = {
    'AWSTemplateFormatVersion': '2010-09-09',
    'Resources': {
        'WebSearchTarget': {
            'Type': 'AWS::BedrockAgentCore::GatewayTarget',
            'Properties': {
                'GatewayIdentifier': gateway_id,
                'Name': 'web-search',
                'Description': 'Web Search target',
                'CredentialProviderConfigurations': [
                    {'CredentialProviderType': 'GATEWAY_IAM_ROLE'}
                ],
                'TargetConfiguration': {
                    'Mcp': {
                        'Connector': {
                            'Source': {'ConnectorId': 'web-search'},
                            'Enabled': ['WebSearch'],
                            'Configurations': [
                                {'Name': 'WebSearch', 'ParameterValues': {}}
                            ]
                        }
                    }
                }
            }
        }
    }
}

with open('/tmp/gateway-target.json', 'w') as f:
    json.dump(template, f, indent=2)
print(f'template written for gateway: {gateway_id}')
