from app_v2 import build_v2_app, default_v2_controller


build_v2_app(default_v2_controller()).launch(
    server_name="0.0.0.0", server_port=6130, quiet=True
)
