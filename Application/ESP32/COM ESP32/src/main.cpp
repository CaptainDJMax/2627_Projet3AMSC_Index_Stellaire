#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>

// UUIDs standards pour le service et la caractéristique (vous pouvez générer les vôtres sur uuidgenerator.net)
#define SERVICE_UUID        "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define CHARACTERISTIC_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"

// Classe qui gère la réception des données de l'application
class MyCallbacks : public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
        String rxValue = pCharacteristic->getValue();
        
        if (rxValue.length() > 0) {
            Serial.print("Donnée reçue de l'app : ");
            for (int i = 0; i < rxValue.length(); i++) {
                Serial.print(rxValue[i]);
            }
            Serial.println();
            
            // --- Ajoutez votre logique ici ---
            // Exemple : if (rxValue == "ON") { allumerLed(); }
        }
    }
};

void setup() {
    Serial.begin(115200);
    delay(2000); // Laisse le temps à l'USB natif de s'initialiser
    Serial.println("Démarrage du BLE...");

    // Initialise l'appareil avec le nom qui apparaîtra sur le téléphone
    BLEDevice::init("ESP32_SuperMini"); 
    
    // Création du serveur et du service
    BLEServer *pServer = BLEDevice::createServer();
    BLEService *pService = pServer->createService(SERVICE_UUID);
    
    // Création de la caractéristique pour la lecture/écriture
    BLECharacteristic *pCharacteristic = pService->createCharacteristic(
                                         CHARACTERISTIC_UUID,
                                         BLECharacteristic::PROPERTY_READ |
                                         BLECharacteristic::PROPERTY_WRITE
                                       );

    // Attache la fonction de callback pour lire les données entrantes
    pCharacteristic->setCallbacks(new MyCallbacks());
    
    // Démarre le service et l'annonce (rend l'ESP32 visible)
    pService->start();
    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    pAdvertising->setScanResponse(true);
    BLEDevice::startAdvertising();
    
    Serial.println("Prêt ! Connectez-vous via l'application.");
}

void loop() {
    // Le traitement BLE se fait en arrière-plan via les callbacks.
    // Vous pouvez placer d'autres tâches ici.
    delay(1000);
}