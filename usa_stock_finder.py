import yfinance as yf


class usa_stock_finder:
    def __init__(self, symbols):
        self.stock_data = yf.download(symbols, period="1y", interval="1d")
        self.symbol_list = symbols
        self.last_high = {}
        self.last_low = {}
        self.current_price = {}
        for symbol in self.symbol_list:
            self.last_high[symbol] = self.stock_data["High"][symbol].max()
            self.current_price[symbol] = self.stock_data["Close"][symbol].iloc[
                -1
            ]
            self.last_low[symbol] = self.stock_data["Low"][symbol].min()

    def is_data_valid(self):
        return not self.stock_data.empty

    def get_current_price(self):
        return self.current_price

    def is_above_75_percent_of_52_week_high(self):
        is_above_75_percent_of_high = {}
        for symbol in self.symbol_list:
            is_above_75_percent_of_high[symbol] = (
                self.current_price[symbol] > self.last_high[symbol] * 0.75
            )

        return is_above_75_percent_of_high

    def is_above_52_week_low(self):
        is_above_low = {}
        for symbol in self.symbol_list:
            increase_percentage = (
                (self.current_price[symbol] - self.last_low[symbol])
                / self.last_low[symbol]
                * 100
            )
            is_above_low[symbol] = increase_percentage >= 30
        return is_above_low

    def get_moving_averages(self, days):
        latest_ma = {}
        for symbol in self.symbol_list:
            hist_data = (
                self.stock_data["Close"][symbol].rolling(window=days).mean()
            )
            latest_ma[symbol] = hist_data.iloc[-1]

        return latest_ma

    def is_200_ma_increasing_recently(self):
        is_increasing = {}
        for symbol in self.symbol_list:
            # Calculate 200-day moving average
            ma_200 = (
                self.stock_data["Close"][symbol].rolling(window=200).mean()
            )

            current_data = ma_200.iloc[-1]
            one_month_ago_data = ma_200.iloc[-21]

            # Check if current moving average is higher than one month ago
            is_increasing[symbol] = current_data >= one_month_ago_data

        return is_increasing

    def has_valid_trend_tempate(self):
        is_above_75_percent_of_high = (
            self.is_above_75_percent_of_52_week_high()
        )
        is_above_low = self.is_above_52_week_low()
        latest_50_ma = self.get_moving_averages(50)
        latest_150_ma = self.get_moving_averages(150)
        latest_200_ma = self.get_moving_averages(200)
        current_price = self.current_price
        is_ma_increasing = self.is_200_ma_increasing_recently()

        valid = {}
        for symbol in self.symbol_list:
            if (
                current_price[symbol] >= latest_150_ma[symbol]
                and current_price[symbol] >= latest_200_ma[symbol]
                and latest_150_ma[symbol] >= latest_200_ma[symbol]
                and is_ma_increasing[symbol]
                and latest_50_ma[symbol] >= latest_150_ma[symbol]
                and latest_50_ma[symbol] >= latest_200_ma[symbol]
                and current_price[symbol] >= latest_50_ma[symbol]
                and is_above_low[symbol]
                and is_above_75_percent_of_high[symbol]
            ):
                valid[symbol] = True
            else:
                valid[symbol] = False

        return valid

    def is_in_phase_2(self, recent_days):
        total_price_volume = {}
        for symbol in self.symbol_list:
            period_data = self.stock_data.tail(recent_days)
            price_diff = period_data["Close"][symbol].diff()
            volume_diff = period_data["Volume"][symbol].diff()
            positive_price_volume = (
                period_data[(price_diff >= 0) & (volume_diff >= 0)].shape[0]
                / period_data.shape[0]
                * 100
            )
            negative_price_volume = (
                period_data[(price_diff < 0) & (volume_diff < 0)].shape[0]
                / period_data.shape[0]
                * 100
            )
            total_price_volume[symbol] = (
                positive_price_volume + negative_price_volume
            )
        return total_price_volume


def main():
    symbols = [
        "HBB",
        "DAKT",
        "DRCT",
        "EGRX",
        "VLGEA",
        "CAAS",
        "WLFC",
        "MCS",
        "VIA",
        "SND",
        "BWEN",
        "VIRC",
        "FPAY",
        "VNCE",
        "PSHG",
        "JAKK",
        "UONE",
        "VTNR",
        "HNRG",
        "OPFI",
    ]
    finder = usa_stock_finder(symbols)
    if finder.is_data_valid():
        has_valid_trend = finder.has_valid_trend_tempate()
        check_phase_2 = finder.is_in_phase_2(200)
        for symbol in symbols:
            if has_valid_trend[symbol]:
                print("Buy " + symbol + " : " + str(check_phase_2[symbol]))
            else:
                print(
                    "Don't buy " + symbol + " : " + str(check_phase_2[symbol])
                )


if __name__ == "__main__":
    main()
