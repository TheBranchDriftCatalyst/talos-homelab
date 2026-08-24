# Proto compilation for Go and Python
#
# Prerequisites:
#   brew install protobuf
#   go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
#   go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
#   pip install grpcio-tools

.PHONY: all go python clean

all: go python

go:
	@echo "Generating Go stubs..."
	@mkdir -p ../go-service/gen/echopb
	protoc --go_out=../go-service/gen/echopb --go_opt=paths=source_relative \
		--go-grpc_out=../go-service/gen/echopb --go-grpc_opt=paths=source_relative \
		echo.proto
	@echo "Done: ../go-service/gen/echopb/"

python:
	@echo "Generating Python stubs..."
	@mkdir -p ../python-service/gen
	python -m grpc_tools.protoc -I. \
		--python_out=../python-service/gen \
		--grpc_python_out=../python-service/gen \
		echo.proto
	@touch ../python-service/gen/__init__.py
	@echo "Done: ../python-service/gen/"

clean:
	rm -rf ../go-service/gen/echopb/*.go
	rm -rf ../python-service/gen/*.py
