"""Interactive configuration manager with INI file support"""
import os
import configparser
import getpass
import sys
from pathlib import Path
from typing import Optional, Dict, Any


class ConfigManager:
    """Manage AIOps configuration with INI file support"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Default: ~/.config/otb_aiops/config.ini
            config_dir = Path.home() / '.config' / 'otb_aiops'
            config_dir.mkdir(parents=True, exist_ok=True)
            self.config_path = config_dir / 'config.ini'

        self.config = configparser.ConfigParser()
        self.load()

    def load(self) -> bool:
        """Load configuration from INI file"""
        if self.config_path.exists():
            try:
                self.config.read(self.config_path)
                return True
            except Exception as e:
                print(f"Failed to load config: {e}", file=sys.stderr)
                return False
        return False

    def save(self):
        """Save configuration to INI file with secure permissions"""
        try:
            with open(self.config_path, 'w') as f:
                self.config.write(f)

            # Set 0600 permissions (owner read/write only)
            if hasattr(os, 'chmod'):
                os.chmod(self.config_path, 0o600)

            print(f"✓ Configuration saved to {self.config_path}")
        except Exception as e:
            print(f"Failed to save config: {e}", file=sys.stderr)
            raise

    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        """Get configuration value"""
        return self.config.get(section, key, fallback=fallback)

    def set(self, section: str, key: str, value: str):
        """Set configuration value"""
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, value)

    def has_section(self, section: str) -> bool:
        """Check if section exists"""
        return self.config.has_section(section)

    def sections(self) -> list:
        """Get all sections"""
        return self.config.sections()

    def interactive_setup(self):
        """Interactive configuration wizard"""
        print("=" * 60)
        print("OpenTenBase AIOps - Configuration Wizard")
        print("=" * 60)
        print()

        # Database Configuration
        print("[1/4] Database Connection")
        print("-" * 60)

        db_host = input(f"OpenTenBase Host [{self.get('database', 'host', 'otb-node1')}]: ").strip()
        self.set('database', 'host', db_host or self.get('database', 'host', 'otb-node1'))

        db_port = input(f"OpenTenBase Port [{self.get('database', 'port', '11003')}]: ").strip()
        self.set('database', 'port', db_port or self.get('database', 'port', '11003'))

        db_user = input(f"Database User [{self.get('database', 'user', 'opentenbase')}]: ").strip()
        self.set('database', 'user', db_user or self.get('database', 'user', 'opentenbase'))

        db_name = input(f"Database Name [{self.get('database', 'name', 'postgres')}]: ").strip()
        self.set('database', 'name', db_name or self.get('database', 'name', 'postgres'))

        # Password (hidden input)
        current_password = self.get('database', 'password', '')
        if current_password:
            change_password = input("Change database password? [y/N]: ").strip().lower()
            if change_password == 'y':
                db_password = getpass.getpass("Database Password: ")
                self.set('database', 'password', db_password)
        else:
            db_password = getpass.getpass("Database Password (optional): ")
            if db_password:
                self.set('database', 'password', db_password)

        print()

        # AI Model Configuration
        print("[2/4] AI Model Configuration")
        print("-" * 60)

        api_key = self.get('ai', 'api_key', '')
        if api_key:
            masked_key = api_key[:8] + '*' * (len(api_key) - 12) + api_key[-4:] if len(api_key) > 12 else '***'
            change_key = input(f"Change API Key? [Current: {masked_key}] [y/N]: ").strip().lower()
            if change_key == 'y':
                api_key = getpass.getpass("AI API Key: ")
                self.set('ai', 'api_key', api_key)
        else:
            api_key = getpass.getpass("AI API Key (DeepSeek/OpenAI): ")
            if api_key:
                self.set('ai', 'api_key', api_key)

        api_base = input(f"API Base URL [{self.get('ai', 'api_base', 'https://api.deepseek.com/v1')}]: ").strip()
        self.set('ai', 'api_base', api_base or self.get('ai', 'api_base', 'https://api.deepseek.com/v1'))

        model = input(f"Model Name [{self.get('ai', 'model', 'deepseek-chat')}]: ").strip()
        self.set('ai', 'model', model or self.get('ai', 'model', 'deepseek-chat'))

        print()

        # Embedding Configuration
        print("[3/4] Embedding Configuration")
        print("-" * 60)

        embedding_key = self.get('embedding', 'api_key', '')
        if embedding_key:
            masked = embedding_key[:8] + '*' * (len(embedding_key) - 12) + embedding_key[-4:] if len(embedding_key) > 12 else '***'
            change_embedding = input(f"Change Embedding API Key? [Current: {masked}] [y/N]: ").strip().lower()
            if change_embedding == 'y':
                embedding_key = getpass.getpass("Embedding API Key: ")
                self.set('embedding', 'api_key', embedding_key)
        else:
            embedding_key = getpass.getpass("Embedding API Key (optional): ")
            if embedding_key:
                self.set('embedding', 'api_key', embedding_key)

        embedding_base = input(f"Embedding API Base [{self.get('embedding', 'api_base', 'https://api.siliconflow.cn/v1')}]: ").strip()
        self.set('embedding', 'api_base', embedding_base or self.get('embedding', 'api_base', 'https://api.siliconflow.cn/v1'))

        embedding_model = input(f"Embedding Model [{self.get('embedding', 'model', 'BAAI/bge-m3')}]: ").strip()
        self.set('embedding', 'model', embedding_model or self.get('embedding', 'model', 'BAAI/bge-m3'))

        print()

        # AIOps Settings
        print("[4/4] AIOps Settings")
        print("-" * 60)

        auto_audit = input(f"Enable periodic health audit? [{self.get('aiops', 'auto_audit_enabled', 'false')}]: ").strip().lower()
        self.set('aiops', 'auto_audit_enabled', auto_audit or self.get('aiops', 'auto_audit_enabled', 'false'))

        if auto_audit in ('true', 'yes', '1'):
            interval = input(f"Audit interval (seconds) [{self.get('aiops', 'auto_audit_interval', '900')}]: ").strip()
            self.set('aiops', 'auto_audit_interval', interval or self.get('aiops', 'auto_audit_interval', '900'))

        distributed = input(f"Enable distributed collection (--all-nodes)? [{self.get('aiops', 'distributed_enabled', 'true')}]: ").strip().lower()
        self.set('aiops', 'distributed_enabled', distributed or self.get('aiops', 'distributed_enabled', 'true'))

        print()

        # Save
        save_confirm = input("Save configuration? [Y/n]: ").strip().lower()
        if save_confirm != 'n':
            self.save()
            print()
            print("=" * 60)
            print("✓ Configuration saved successfully!")
            print(f"  Location: {self.config_path}")
            print("=" * 60)
        else:
            print("Configuration not saved.")

    def to_env_dict(self) -> Dict[str, str]:
        """Convert INI config to environment variable dict"""
        env_dict = {}

        # Database
        if self.has_section('database'):
            env_dict['DB_HOST'] = self.get('database', 'host', 'otb-node1')
            env_dict['DB_PORT'] = self.get('database', 'port', '11003')
            env_dict['DB_USER'] = self.get('database', 'user', 'opentenbase')
            env_dict['DB_NAME'] = self.get('database', 'name', 'postgres')
            env_dict['DB_PASSWORD'] = self.get('database', 'password', '')

        # AI
        if self.has_section('ai'):
            env_dict['DEEPSEEK_API_KEY'] = self.get('ai', 'api_key', '')
            env_dict['DEEPSEEK_API_BASE'] = self.get('ai', 'api_base', 'https://api.deepseek.com/v1')
            env_dict['DEEPSEEK_MODEL'] = self.get('ai', 'model', 'deepseek-chat')

        # Embedding
        if self.has_section('embedding'):
            env_dict['EMBEDDING_API_KEY'] = self.get('embedding', 'api_key', '')
            env_dict['EMBEDDING_API_BASE'] = self.get('embedding', 'api_base', 'https://api.siliconflow.cn/v1')
            env_dict['EMBEDDING_MODEL'] = self.get('embedding', 'model', 'BAAI/bge-m3')

        # AIOps
        if self.has_section('aiops'):
            env_dict['AIOPS_AUTO_AUDIT_ENABLED'] = self.get('aiops', 'auto_audit_enabled', 'false')
            env_dict['AIOPS_AUTO_AUDIT_INTERVAL_SECONDS'] = self.get('aiops', 'auto_audit_interval', '900')
            env_dict['AIOPS_DISTRIBUTED_ENABLED'] = self.get('aiops', 'distributed_enabled', 'true')

        return env_dict

    def apply_to_env(self):
        """Apply configuration to environment variables"""
        env_dict = self.to_env_dict()
        for key, value in env_dict.items():
            if value:
                os.environ[key] = value


def main():
    """CLI entry point for configuration"""
    import argparse

    parser = argparse.ArgumentParser(description='OpenTenBase AIOps Configuration Manager')
    parser.add_argument('--setup', action='store_true', help='Run interactive setup wizard')
    parser.add_argument('--show', action='store_true', help='Show current configuration (masked)')
    parser.add_argument('--path', type=str, help='Custom config file path')

    args = parser.parse_args()

    config_mgr = ConfigManager(args.path)

    if args.setup:
        config_mgr.interactive_setup()
    elif args.show:
        if not config_mgr.config_path.exists():
            print("No configuration file found.")
            print(f"Run '{sys.argv[0]} --setup' to create one.")
            sys.exit(1)

        print("=" * 60)
        print("Current Configuration")
        print("=" * 60)
        print()

        for section in config_mgr.sections():
            print(f"[{section}]")
            for key, value in config_mgr.config.items(section):
                # Mask sensitive values
                if 'password' in key.lower() or 'key' in key.lower():
                    if value:
                        masked = value[:4] + '*' * (len(value) - 8) + value[-4:] if len(value) > 8 else '***'
                        print(f"  {key} = {masked}")
                    else:
                        print(f"  {key} = (not set)")
                else:
                    print(f"  {key} = {value}")
            print()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
