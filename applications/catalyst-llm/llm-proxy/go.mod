module github.com/TheBranchDriftCatalyst/talos-homelab/tools/llm-proxy

go 1.22

require (
	github.com/aws/aws-sdk-go-v2/config v1.28.7
	github.com/aws/aws-sdk-go-v2/service/ec2 v1.198.1
	github.com/google/uuid v1.6.0
	github.com/gorilla/websocket v1.5.3
	github.com/rabbitmq/amqp091-go v1.10.0
)

replace github.com/thebranchdriftcatalyst/ec2-agent => ../../../tools/ec2-agent

require (
	github.com/aws/aws-sdk-go-v2 v1.32.7 // indirect
	github.com/aws/aws-sdk-go-v2/credentials v1.17.48 // indirect
	github.com/aws/aws-sdk-go-v2/feature/ec2/imds v1.16.22 // indirect
	github.com/aws/aws-sdk-go-v2/internal/configsources v1.3.26 // indirect
	github.com/aws/aws-sdk-go-v2/internal/endpoints/v2 v2.6.26 // indirect
	github.com/aws/aws-sdk-go-v2/internal/ini v1.8.1 // indirect
	github.com/aws/aws-sdk-go-v2/service/internal/accept-encoding v1.12.1 // indirect
	github.com/aws/aws-sdk-go-v2/service/internal/presigned-url v1.12.7 // indirect
	github.com/aws/aws-sdk-go-v2/service/sso v1.24.8 // indirect
	github.com/aws/aws-sdk-go-v2/service/ssooidc v1.28.7 // indirect
	github.com/aws/aws-sdk-go-v2/service/sts v1.33.3 // indirect
	github.com/aws/smithy-go v1.22.1 // indirect
	github.com/thebranchdriftcatalyst/ec2-agent v0.0.0-00010101000000-000000000000 // indirect
)
