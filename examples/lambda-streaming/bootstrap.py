"""Custom Runtime API bootstrap for native Python response streaming."""

from hayate.adapters.aws import run_lambda_streaming

from app import app

run_lambda_streaming(app)
