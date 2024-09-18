import os

FILES_DIR = 'app/auth'
files = os.listdir(FILES_DIR)

def get_file_path(file_name):
    return os.path.join(FILES_DIR, file_name)

def check_file_exists(file_path):
    return os.path.isfile(file_path)