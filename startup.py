from util.db_util import get_table_name, initialize_db
from util.global_variables import INTRADAY_M5_CANDLE_SIZE, INTRADAY_M15_CANDLE_SIZE


def run_startup():
    # init 5 min backend data storage
    table_name = get_table_name(f"m{INTRADAY_M5_CANDLE_SIZE}")
    initialize_db(table_name)

    # init 15 min backend data storage
    table_name = get_table_name(f"m{INTRADAY_M15_CANDLE_SIZE}")
    initialize_db(table_name)

    # init daily candle backend data storage
    table_name = get_table_name("d1")
    initialize_db(table_name)


if __name__ == "__main__":
    run_startup()
