#include <iostream>
#include <vector>
#include <thread>
#include <chrono>
#include <stdexcept>
#include <cmath>

#include <iostream>
#include <fstream>
#include <string>
#include <ctime>
#include <unordered_map>
#include <base64.h>
#include "PrivateKey.h"
#include <curl/curl.h> // Include the cURL library for HTTP requests
#include <json/json.h> // Include a JSON library for handling JSON data

// Log message to a file
void logToFile(const std::string& message) {
    // Get today's date
    std::time_t now = std::time(nullptr);
    char dateBuffer[11]; // Format: YYYY-MM-DD
    std::strftime(dateBuffer, sizeof(dateBuffer), "%Y-%m-%d", std::localtime(&now));

    // Create log file name with today's date
    std::string logFileName = std::string(dateBuffer) + "-monitor.log";

    // Open the log file in append mode
    std::ofstream logFile(logFileName, std::ios_base::app);
    
    if (logFile.is_open()) {
        // Get the current time
        char timeBuffer[100];
        std::strftime(timeBuffer, sizeof(timeBuffer), "%H:%M:%S", std::localtime(&now));

        // Write timestamp and message to the file
        logFile << "[" << dateBuffer << " " << timeBuffer << "] " << message << std::endl;
    } else {
        std::cerr << "Failed to open log file!" << std::endl;
    }
}




double getLatestPrice(const std::string& stock) {
    // Placeholder implementation

    return 0.0; // Replace with actual logic
}

void recordTransaction(int user_id, const std::string& stock, const std::string& action, double amount) {
    //output stockname buy sell 
}

double orderBuyMarket(const std::string& stock, int quantity) {
    // Placeholder implementation
    return 0.0; // Replace with actual logic
}

double orderSellMarket(const std::string& stock, int quantity) {
    // Placeholder implementation
    return 0.0; // Replace with actual logic
}

class ApiClient {
public:
    std::string api_key;
    PrivateKey private_key;
    std::string base_url; // Base URL for the API

    std::unordered_map<std::string, std::string> getAuthorizationHeader(
        const std::string& method, 
        const std::string& path, 
        const std::string& body, 
        int timestamp) 
    {
        std::string messageToSign = api_key + std::to_string(timestamp) + path + method + body;

        auto signedMessage = private_key.sign(messageToSign);

        std::unordered_map<std::string, std::string> headers;
        headers["x-api-key"] = api_key;
        headers["x-signature"] = base64_encode(signedMessage.signature);
        headers["x-timestamp"] = std::to_string(timestamp);

        return headers;
    }

    long _get_current_timestamp() {
        // Implement a method to get the current timestamp
        return static_cast<long>(std::time(nullptr));
    }

    Json::Value makeApiRequest(const std::string& method, const std::string& path, const std::string& body = "") {
        long timestamp = _get_current_timestamp();
        auto headers = getAuthorizationHeader(method, path, body, timestamp);
        std::string url = base_url + path;

        CURL* curl;
        CURLcode res;
        Json::Value jsonResponse;

        curl = curl_easy_init();
        if(curl) {
            struct curl_slist* chunk = NULL;
            for (const auto& header : headers) {
                std::string headerString = header.first + ": " + header.second;
                chunk = curl_slist_append(chunk, headerString.c_str());
            }
            curl_easy_setopt(curl, CURLOPT_HTTPHEADER, chunk);
            curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
            curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);

            if (method == "POST") {
                curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
            }

            // Perform the request
            res = curl_easy_perform(curl);
            if (res != CURLE_OK) {
                std::cerr << "Error making API request: " << curl_easy_strerror(res) << std::endl;
                jsonResponse = Json::Value(); // Return an empty JSON value on error
            } else {
                // Handle the response (assuming you have a function to parse JSON)
                // You would need to implement a way to read the response into jsonResponse
            }

            // Cleanup
            curl_slist_free_all(chunk);
            curl_easy_cleanup(curl);
        }
        return jsonResponse; // Return the JSON response
    }

    // New method to get estimated price
    Json::Value get_estimated_price(const std::string& symbol, const std::string& side, const std::string& quantity) {
        std::string path = "/api/v1/crypto/marketdata/estimated_price/?symbol=" + symbol + "&side=" + side + "&quantity=" + quantity;
        return makeApiRequest("GET", path);
    }

    // New method to place an order
    Json::Value placeOrder(
        const std::string& client_order_id,
        const std::string& side,
        const std::string& order_type,
        const std::string& symbol,
        const std::unordered_map<std::string, std::string>& order_config
    ) {
        Json::Value body;
        body["client_order_id"] = client_order_id;
        body["side"] = side;
        body["type"] = order_type;
        body["symbol"] = symbol;
        body[order_type + "_order_config"] = Json::Value(Json::objectValue); // Create an object for order_config

        for (const auto& config : order_config) {
            body[order_type + "_order_config"][config.first] = config.second;
        }

        std::string path = "/api/v1/crypto/trading/orders/";
        return makeApiRequest("POST", path, Json::writeString(Json::StreamWriterBuilder(), body));
    }

    
};



int DAYCOUNT = 0;

// Define a struct to hold buy and sell values
struct TransactionResult {
    double buyValue;
    double sellValue;
};

TransactionResult monitorBuy(const std::string& stock, bool dry, int user_id, double average) {
    std::vector<double> prices;
    double diff = 0.0;
    
    // Initialize a TransactionResult struct to return
    TransactionResult result = {0.0, 0.0}; // {buyValue, sellValue}

    try {
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

        // Update the result struct with buy and sell values
        result.buyValue = costBuy; // cost of the buy
        result.sellValue = sellprice; // price at which stock was sold

    } catch (const std::exception& e) {
        std::cerr << "Error in monitorBuy: " << e.what() << std::endl;
        diff = 0;
    }
    return result; // Return the struct
}

int main() {
    // Example log messages
    logToFile("Application started.");
    logToFile("Processing data...");
    logToFile("An error occurred while accessing the database.");

    std::cout << "Logs have been written to application.log" << std::endl;
    return 0;
}