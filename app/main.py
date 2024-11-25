from fastapi import FastAPI, HTTPException
from uuid import uuid4
import psycopg2
import hvac
from dotenv import load_dotenv
import os
from models.models import ConnectionInput,ConnectionOutput
import logging
import time
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# load_dotenv()
app = FastAPI()

DB_NAME = os.getenv('POSTGRES_DB', 'cogneotech')
USER = os.getenv('POSTGRES_USER', 'postgres')
PASSWORD = os.getenv('POSTGRES_PASSWORD', 'password')
HOST = os.getenv('POSTGRES_HOST', 'db') 
PORT = os.getenv('POSTGRES_PORT', 5432)

VAULT_ADDR = os.getenv('VAULT_ADDR', 'http://vault:8200')
VAULT_TOKEN = os.getenv('VAULT_TOKEN', 'root')


# vault_client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
# if not vault_client.is_authenticated():
#     raise RuntimeError("Failed to authenticate with HashiCorp Vault")


# def get_db_connection():
#     """Establish connection with PostgreSQL database."""
#     try:
#         connection = psycopg2.connect(
#             dbname=DB_NAME, 
#             user=USER, 
#             password=PASSWORD, 
#             host=HOST, 
#             port=PORT
#         )
#         return connection
#     except Exception as e:
#         logger.error(f"Database connection error: {str(e)}")
#         raise HTTPException(status_code=500, detail="Internal Server Error")
  

# def init_db():
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     try:
#         cursor.execute("""
#             CREATE TABLE IF NOT EXISTS connection (
#                 id UUID PRIMARY KEY,
#                 host VARCHAR(255) NOT NULL,
#                 port INT NOT NULL,
#                 username VARCHAR(255) NOT NULL UNIQUE
#             )
#         """)
#         conn.commit()
#     except Exception as e:
#         logger.error(f"Error initializing database: {str(e)}")
#     finally:
#         cursor.close()
#         conn.close()

# init_db()


def connect_to_vault(max_retries: int = 8, retry_delay: int = 5) -> hvac.Client:
    """
    Initialize Vault client
    """
    for attempt in range(max_retries):
        try:
            client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
            if client.is_authenticated():
                logger.info(f"Successfully connected to Vault on attempt {attempt + 1}")
                return client
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to connect to Vault after {max_retries} attempts: {str(e)}")
                raise RuntimeError("Failed to authenticate with HashiCorp Vault")
            logger.warning(f"Vault connection attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

def get_db_connection(max_retries: int = 8, retry_delay: int = 5) -> psycopg2.extensions.connection:
    """
    Establish connection with PostgreSQL database
    """
    for attempt in range(max_retries):
        try:
            connection = psycopg2.connect(
                dbname=DB_NAME, 
                user=USER, 
                password=PASSWORD, 
                host=HOST, 
                port=PORT
            )
            logger.info(f"Successfully connected to database on attempt {attempt + 1}")
            return connection
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Database connection error after {max_retries} attempts: {str(e)}")
                raise HTTPException(status_code=500, detail="Internal Server Error")
            logger.warning(f"Database connection attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)


vault_client = connect_to_vault()

def init_db():
    """Initialize database """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS connection (
                id UUID PRIMARY KEY,
                host VARCHAR(255) NOT NULL,
                port INT NOT NULL,
                username VARCHAR(255) NOT NULL UNIQUE
            )
        """)
        conn.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise
    finally:
        cursor.close()
        conn.close()

def initialize_application():
    max_retries = 5
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            init_db()
            logger.info("Application initialized successfully")
            return
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to initialize application after {max_retries} attempts: {str(e)}")
                raise
            logger.warning(f"Initialization attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)


initialize_application()

def save_connection_to_db(host: str, port: int, username: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    connection_id = str(uuid4())
    try:
        cursor.execute("SELECT id FROM connection WHERE username = %s", (username,))
        existing_user = cursor.fetchone()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already exists. Please choose a different username.")
        
        cursor.execute(
            "INSERT INTO connection (id, host, port, username) VALUES (%s, %s, %s, %s)",
            (connection_id, host, port, username)
        )
        conn.commit()
    except HTTPException as e:
        raise e    
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving to database: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        cursor.close()
        conn.close()
    return connection_id

def store_password_in_vault(connection_id: str, password: str):
    """Store the password in HashiCorp Vault using connection ID"""
    try:
        vault_client.secrets.kv.v2.create_or_update_secret(
            path=f"connection/{connection_id}",
            secret={"password": password}
        )
    except Exception as e:
        logger.error(f"Error storing password in Vault: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    
def retrieve_password_from_vault(connection_id: str) -> str:
    """Retrieve the password from HashiCorp Vault using the connection ID."""
    try:
        secret = vault_client.secrets.kv.v2.read_secret_version(path=f"connection/{connection_id}")
        return secret["data"]["data"].get("password")
    except Exception as e:
        logger.error(f"Password not found in Vault: {str(e)}")
        raise HTTPException(status_code=404, detail="Password not found")

   
@app.post("/connection", status_code=201, response_model=ConnectionOutput)
def create_connection(connection: ConnectionInput):
    """Endpoint to save data to the database and the password to Vault """
    
    connection_id = save_connection_to_db(connection.host, connection.port, connection.username)
    store_password_in_vault(connection_id, connection.password)
    return ConnectionOutput(
        id=connection_id,
        host=connection.host,
        port=connection.port,
        username=connection.username
    )
    
@app.get("/connection/{connection_id}", response_model=ConnectionInput)
def get_connection(connection_id: str):
    """ Endpoint to fetche data from the database and password from Vault """
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, host, port, username FROM connection WHERE id = %s", (connection_id,))
        record = cursor.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="Connection not found")

        password = retrieve_password_from_vault(connection_id)
        return ConnectionInput(
            host=record[1],
            port=record[2],
            username=record[3],
            password=password
        )
    except HTTPException as e:
        logger.error(f"Error in get_connection: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in get_connection: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    


