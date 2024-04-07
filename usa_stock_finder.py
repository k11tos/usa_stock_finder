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
        is_increasing_with_volume_and_price = (
            self.compare_volume_price_movement(200)
        )

        valid = {}
        for symbol in self.symbol_list:
            valid[symbol] = (
                current_price[symbol] >= latest_150_ma[symbol]
                and current_price[symbol] >= latest_200_ma[symbol]
                and latest_150_ma[symbol] >= latest_200_ma[symbol]
                and is_ma_increasing[symbol]
                and latest_50_ma[symbol] >= latest_150_ma[symbol]
                and latest_50_ma[symbol] >= latest_200_ma[symbol]
                and current_price[symbol] >= latest_50_ma[symbol]
                and is_above_low[symbol]
                and is_above_75_percent_of_high[symbol]
                and is_increasing_with_volume_and_price[symbol]
            )

        return valid

    def price_volume_correlation_percent(self, recent_days):
        total_price_volume = {}
        period_data = self.stock_data.tail(recent_days)
        for symbol in self.symbol_list:
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

    def compare_volume_price_movement(self, recent_days):
        period_data = self.stock_data.tail(recent_days)
        comparison_result = {}
        for symbol in self.symbol_list:
            average_volume = period_data["Volume"][symbol].mean()
            volume_data = period_data["Volume"][symbol]
            price_diff_data = period_data["Close"][symbol].diff()
            volume_up_days = volume_data[volume_data > average_volume]
            price_up_days = volume_up_days[(price_diff_data >= 0)].shape[0]
            price_down_days = volume_up_days[price_diff_data < 0].shape[0]
            comparison_result[symbol] = price_up_days >= price_down_days
        return comparison_result


def main():
    symbols = [
        "CINT",
        "SIGA",
        "TAST",
        "EGRX",
        "AMLX",
        "BRY",
        "SHIP",
        "BWEN",
        "PPIH",
        "KTCC",
        "CMPO",
        "GLDD",
        "VNCE",
        "AP",
        "CVGI",
        "PSHG",
        "PBYI",
        "CRWS",
        "CRCT",
        "DCGO",
        "ESOA",
        "MNTX",
        "SRTS",
        "FF",
        "ULBI",
        "FTK",
        "TZOO",
        "BRLT",
        "STGW",
        "HLLY",
        "STKS",
        "PFIE",
        "HGBL",
        "LINC",
        "GAMB",
        "CAAS",
        "DXLG",
        "OIS",
        "JVA",
        "AGS",
        "GLBS",
        "TORO",
        "STCN",
        "SGMA",
        "SWAG",
        "CTRM",
        "ARBB",
        "VMEO",
        "TK",
        "DHX",
        "MNDO",
        "RAYA",
        "VMD",
        "CACO",
        "GDHG",
        "MHUA",
        "LICN",
        "EDUC",
        "CHGG",
        "GASS",
        "VCIG",
        "TSRI",
        "HLP",
        "LOCO",
        "SB",
        "JYD",
        "GPRK",
        "OPXS",
        "RTC",
        "SLNG",
        "STBX",
        "SOI",
        "FPAY",
        "JCTCF",
        "ITI",
        "APWC",
        "SOTK",
        "GILT",
        "STRR",
        "PAYS",
        "MRAM",
        "CTLP",
        "EGAN",
        "WILC",
        "UG",
        "OPAL",
        "PXS",
        "ISSC",
        "PANL",
        "PCYO",
        "IMPP",
        "TLF",
        "ELSE",
        "KODK",
        "DSX",
        "AGMH",
        "ADTH",
        "OSUR",
        "DENN",
        "TTSH",
    ]
    finder = usa_stock_finder(symbols)
    if finder.is_data_valid():
        has_valid_trend = finder.has_valid_trend_tempate()
        strong_in_200 = finder.price_volume_correlation_percent(200)
        strong_in_100 = finder.price_volume_correlation_percent(100)
        strong_in_50 = finder.price_volume_correlation_percent(50)
        for symbol in symbols:
            if has_valid_trend[symbol] and strong_in_50[symbol] >= 50:
                print(
                    "Buy "
                    + symbol
                    + " : "
                    + str(strong_in_200[symbol])
                    + " : "
                    + str(strong_in_100[symbol])
                    + " : "
                    + str(strong_in_50[symbol])
                )


if __name__ == "__main__":
    main()
