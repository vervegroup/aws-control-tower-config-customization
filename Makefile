install_dependencies:
	pip install -r requirements.txt -t boto3

compress_files:
	zip -r0 config-recoder-lambda-src.zip boto3 ct_configrecorder_override_consumer.py ct_configrecorder_override_producer.py cfnresource.py delete.py

all: install_dependencies compress_files