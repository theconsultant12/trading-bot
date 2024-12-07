#include <iostream>
#include <vector>
#include <thread>
#include <chrono>
#include <stdexcept>
#include <cmath>

// Assuming these functions are defined elsewhere
double getWeightedAverage(const std::string& stock);
double getLatestPrice(const std::string& stock);
void recordTransaction(int user_id, const std::string& stock, const std::string& action, double amount);
double orderBuyMarket(const std::string& stock, int quantity);
double orderSellMarket(const std::string& stock, int quantity);
int DAYCOUNT = 0;

double monitorBuy(const std::string& stock, bool dry, int user_id) {
    std::vector<double> prices;
    double diff = 0.0;
    try {
        double average = getWeightedAverage(stock);
        std::cout << "Average: " << average << std::endl;
        int quantity = static_cast<int>(500 / average);
        int count = 0;
        std::cout << "Waiting for price to drop. Average is " << average << " current price is " << getLatestPrice(stock) << std::endl;

        while (getLatestPrice(stock) > average - (average * 0.0012)) {
            count++;
            DAYCOUNT++;
            std::this_thread::sleep_for(std::chrono::seconds(2));
            if (count % 49 == 0) {
                std::this_thread::sleep_for(std::chrono::seconds(10));
            }
        }

        double costBuy;
        if (dry) {
            costBuy = getLatestPrice(stock);
            recordTransaction(user_id, stock, "buy", costBuy * quantity);
            std::cout << quantity << " stock bought at " << costBuy << " after checking " << count << " times" << std::endl;
        } else {
            costBuy = orderBuyMarket(stock, quantity);
            recordTransaction(user_id, stock, "buy", costBuy * quantity);
            std::cout << quantity << " stock bought at " << costBuy << " after checking " << count << " times" << std::endl;
        }

        std::this_thread::sleep_for(std::chrono::seconds(10));
        count = 0;
        std::cout << "Waiting for price to rise. Current price is " << getLatestPrice(stock) << " average is " << average << std::endl;

        while (getLatestPrice(stock) < average + (average * 0.0012)) {
            count++;
            DAYCOUNT++;
            std::this_thread::sleep_for(std::chrono::seconds(2));
            if (count % 49 == 0) {
                std::this_thread::sleep_for(std::chrono::seconds(10));
            }
        }

        double sellprice;
        if (dry) {
            sellprice = getLatestPrice(stock);
            std::cout << "Stock sold at " << sellprice << " after checking " << count << " times" << std::endl;
            recordTransaction(user_id, stock, "sell", sellprice * quantity);
            diff = sellprice - costBuy;
        } else {
            sellprice = orderSellMarket(stock, quantity);
            recordTransaction(user_id, stock, "sell", sellprice * quantity);
            std::cout << "Stock sold at " << sellprice << " after checking " << count << " times" << std::endl;
            diff = (sellprice * quantity) - (costBuy * quantity);
        }

        std::cout << "We made " << diff << " on this sale" << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Error in monitorBuy: " << e.what() << std::endl;
        diff = 0;
    }
    return diff;
}
