#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: |
  Aggiungere feature di geolocalizzazione:
  1. Al primo accesso all'app chiedere il permesso GPS (con fallback su città manuale se negato).
  2. Nel Profilo, slider 1-100 km (default 30) per filtrare i gruppi per distanza.
  3. In "Crea gruppo" aggiungere due campi obbligatori: Città e Via.
  4. Il backend deve geocodificare Città+Via via Nominatim OSM (no API key).
  5. Il feed deve filtrare per raggio con formula Haversine.

backend:
  - task: "Geocoding via Nominatim + Città/Via obbligatori nella creazione gruppo"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Aggiunti campi city/street/lat/lon al modello Group; POST /api/groups ora
          richiede city+street (400 se vuoti) e geocodifica via Nominatim con
          throttle 1req/s + cache in-memory. Se Nominatim fallisce il gruppo viene
          comunque creato con lat/lon=None. Aggiunti anche city/street alla
          moderation check.
  - task: "Filtro feed per distanza (Haversine) su GET /api/groups"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          GET /api/groups accetta lat/lon/radius_km (1..100). Groups senza
          coordinate sono INCLUSI (backward-compat con gruppi pre-migrazione),
          quelli con coords sono filtrati con haversine.
  - task: "Endpoint GET /api/geocode per città di riferimento manuale"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Nuovo endpoint pubblico GET /api/geocode?city=&street= che restituisce
          {lat, lon} usando Nominatim. 404 se indirizzo non trovato.
          Verifica manuale curl: Milano+Via Torino -> 45.4637,9.1881 ✓

frontend:
  - task: "Richiesta permessi GPS al primo accesso (modal + fallback città)"
    implemented: true
    working: true
    file: "/app/frontend/src/contexts/location.tsx, /app/frontend/app/(tabs)/index.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Nuovo LocationProvider con AsyncStorage per persistenza. Modal
          contestuale mostrato al primo bootstrap sulla home con 3 opzioni:
          "Usa la mia posizione" (GPS), "Inserisci una città" (Nominatim),
          "Salta, mostra tutti". Gestito canAskAgain -> Linking.openSettings().
          Verificato via screenshot: modal appare correttamente e il flusso
          "Milano" imposta il filtro "Entro 30 km da Milano".
  - task: "Slider distanza 1-100 km (default 30) nel Profilo"
    implemented: true
    working: true
    file: "/app/frontend/app/(tabs)/profile.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Sezione "Distanza gruppi" con @react-native-community/slider (1..100,
          step=1, default 30). Badge live "N km" + stato posizione (GPS attivo /
          Riferimento città / non impostata). Pulsanti "Usa GPS", "Città" (form
          inline con conferma Nominatim), "Rimuovi".
  - task: "Campi Città/Via obbligatori nel form Crea Gruppo"
    implemented: true
    working: true
    file: "/app/frontend/app/(tabs)/create.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Aggiunti due input dedicati (testID city-input e street-input) sotto
          il campo LUOGO. Validazione client + server. Anche moderati per
          contenuti vietati.

metadata:
  created_by: "main_agent"
  version: "1.1"
  test_sequence: 11
  run_ui: true

test_plan:
  current_focus:
    - "Geocoding via Nominatim + Città/Via obbligatori nella creazione gruppo"
    - "Filtro feed per distanza (Haversine) su GET /api/groups"
    - "Endpoint GET /api/geocode per città di riferimento manuale"
    - "Richiesta permessi GPS al primo accesso (modal + fallback città)"
    - "Slider distanza 1-100 km (default 30) nel Profilo"
    - "Campi Città/Via obbligatori nel form Crea Gruppo"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "testing"
    message: |
      Iteration 11: tutti i 15 nuovi test backend (city/street mandatory,
      geocoding Milano, radius 5km/1km, backward-compat, /api/geocode) sono
      PASSED. Frontend web: modal permessi, banner "Entro 30 km da Milano",
      persistenza AsyncStorage, slider 30km nel profilo, input city/street
      nel form Crea: TUTTI VERIFICATI. Nessun blocco.
  - agent: "main"
    message: |
      Implementata geolocalizzazione completa (backend + frontend).
      Backend: geocoding Nominatim + filtro Haversine + endpoint /geocode.
      Frontend: LocationProvider + modal permessi + slider profilo + input
      city/street in creazione gruppo. Il flusso web mostrato funziona
      (screenshot confermano modal, banner distanza, slider profilo, form).

      Per il testing: usare device_id "TESTDEV_" prefix (già in white-list nel
      backend) o generare UUID dev_hex32. Nominatim ha throttle 1req/s: nei
      test creare i gruppi con pause di ~1.2s tra chiamate consecutive.
      Verificare specialmente:
        a) POST /api/groups senza city -> 400 "Inserisci la città"
        b) POST /api/groups senza street -> 400 "Inserisci la via"
        c) POST /api/groups con Milano+Via Torino -> lat/lon popolati
        d) GET /api/groups?lat=45.46&lon=9.18&radius_km=5 filtra correttamente
        e) GET /api/groups (senza geo) include tutti (regressione)
        f) GET /api/geocode?city=Milano -> {lat, lon}
        g) GET /api/geocode?city=CittaInesistente -> 404

# ============================== Iteration 12 ==============================

user_problem_statement: |
  Ulteriori miglioramenti alla feature di posizione:
  1. Quando si crea un gruppo, mentre si digita il nome della città l'app
     deve suggerire città reali con la provincia a fianco.
  2. Una volta creato il gruppo, il titolo/riga di posizione deve mostrare
     città (e provincia) accanto al luogo.
  3. RIMUOVERE il campo VIA dal form di creazione.

backend:
  - task: "Endpoint /api/cities/suggest con autocomplete Photon"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Nuovo endpoint GET /api/cities/suggest?q= che usa Photon (Komoot)
          OSM autocomplete (supporta prefix search). Filtra countrycode=IT,
          osm_key=place, osm_value in {city,town,village,hamlet}. Cache
          in-memory. Verificato via curl: "correg" -> Correggio, "mila"
          -> Milano+Milazzo+Milanere, "rom" -> Roma+Romano Canavese+...
  - task: "Rimozione campo street obbligatorio; province+lat+lon dal client"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          POST /api/groups: rimosso `street`, aggiunti `province`, `lat`, `lon`
          opzionali. Se lat/lon forniti dal client (autocomplete pick), il
          backend li usa senza rifare geocoding. Altrimenti fallback su
          `_geocode(city)`. `street` non è più incluso nel modello Group.

frontend:
  - task: "Componente CityAutocomplete riutilizzabile"
    implemented: true
    working: true
    file: "/app/frontend/src/components/CityAutocomplete.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Nuovo componente debounced (350ms), sequence-tracking anti-race,
          dropdown con "Nome" + "Provincia · Regione". Sceglie suggestion
          -> setta lat/lon per skip-geocode nel backend.
  - task: "Form Crea Gruppo: rimozione VIA + autocomplete città"
    implemented: true
    working: true
    file: "/app/frontend/app/(tabs)/create.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Rimosso input VIA. CITTÀ ora usa CityAutocomplete. Il payload al
          create manda city+province+lat+lon dalla selezione. Validazione:
          si deve SELEZIONARE una città dal menu (non basta digitare).
          Verificato via UI: Milano selezionata -> gruppo creato con
          "Bar Rita · Milano (Milano)" nel detail.
  - task: "Home + Profilo: autocomplete città manuale (fallback GPS negato)"
    implemented: true
    working: true
    file: "/app/frontend/app/(tabs)/index.tsx, /app/frontend/app/(tabs)/profile.tsx, /app/frontend/src/contexts/location.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          LocationProvider.setManualLocation ora accetta coords opzionali
          {lat, lon, province} dal picker. Il modal della home e la sezione
          "Città" del profilo usano CityAutocomplete. Nuovo campo
          `manualProvince` nelle prefs. Banner mostra "Entro N km da CITTÀ".
  - task: "Visualizzazione città+provincia nelle card e nel detail"
    implemented: true
    working: true
    file: "/app/frontend/app/(tabs)/index.tsx, /app/frontend/app/group/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Card home + detail group ora renderizzano
          `location · city (province)` con `.filter(Boolean).join(" · ")`
          per gestire i gruppi legacy senza `city`/`province`.

metadata:
  created_by: "main_agent"
  version: "1.2"
  test_sequence: 12
  run_ui: true

test_plan:
  current_focus:
    - "Endpoint /api/cities/suggest con autocomplete Photon"
    - "Rimozione campo street obbligatorio; province+lat+lon dal client"
    - "Componente CityAutocomplete riutilizzabile"
    - "Form Crea Gruppo: rimozione VIA + autocomplete città"
    - "Home + Profilo: autocomplete città manuale (fallback GPS negato)"
    - "Visualizzazione città+provincia nelle card e nel detail"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Iterazione 12: autocomplete città con Photon. Rimosso VIA. Aggiunta
      province ovunque. Backend endpoints:
        GET /api/cities/suggest?q=milan -> [{name, province, region, lat, lon, display}]
        POST /api/groups accetta {city, province?, lat?, lon?} (no street)
      Test manuale via curl e UI OK.

# ============================== Iteration 13 ==============================

user_problem_statement: |
  Quando si crea un gruppo il numero minimo di partecipanti deve essere
  almeno 3.

backend:
  - task: "Vincolo min_participants>=3 sul POST /api/groups"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Aggiornato GroupCreate: min_participants Field(ge=3, le=200) e
          max_participants Field(ge=3, le=200). Test manuale: payload con
          min=2 -> 422 (Unprocessable Entity, Pydantic). min=3 -> 200.

frontend:
  - task: "Default min=3 + validazione client + hint UI"
    implemented: true
    working: true
    file: "/app/frontend/app/(tabs)/create.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Default minPart="3" (era "2"). reset() usa "3". Validazione:
          minP<3 -> "Il numero minimo di partecipanti è 3", maxP<3 ->
          "Il numero massimo di partecipanti è 3". Nuovo hint sotto la
          label "Minimo 3 persone per gruppo". Placeholder Min="3" e
          Max="8" sui campi numerici.

metadata:
  created_by: "main_agent"
  version: "1.3"
  test_sequence: 13
  run_ui: true

test_plan:
  current_focus:
    - "Vincolo min_participants>=3 sul POST /api/groups"
    - "Default min=3 + validazione client + hint UI"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Iterazione 13 (micro-feature): min 3 partecipanti per creare un gruppo.
      Backend: Field(ge=3). Frontend: default 3, validazione client, hint UI.
