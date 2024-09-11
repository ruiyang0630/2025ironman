cd $(dirname $(realpath $0))
if [[ ! -f "$(dirname $(realpath $0))/config.py" ]]; then
    echo 2> "config.py not found. Please create one from config-example.py and fill in the required fields."
    exit 1
fi

poetry run python monitor.py