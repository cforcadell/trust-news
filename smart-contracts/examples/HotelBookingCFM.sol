// SPDX-License-Identifier: MIT
pragma solidity ^0.8.18;

// Libraries

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/utils/Strings.sol";
import "hardhat/console.sol";


/**
 * @title Ejercicio 1. Hotel booking contract
 * @notice Do not use this contract in production
 */
contract HotelBooking {

    //tipus de habitació
    enum RoomType {Single, Double, Suite}
    
    //Estructura de dades d'una reserva
    struct Reserva{
        address customer;
        RoomType roomType;
        uint bookingDays;
    } 

    //Estructura de dades d'un hotel
    struct Hotel{
        uint basePricePerDay;
        bool registered;
        Reserva[] bookings;
    }

    // Variables Global(Storage) 
    //Propietari del contracte
    address public owner;
    //Declarem una variable global en forma de  mapping entre el nom dels hotels i l'estructura de dades. 
    mapping (string => Hotel) public  hotels;
    //variable (hpContract) que emmagatzema la direcció/instància del contracte ERC20. Aquesta variable ha d'inicialitzar-sea l'hora de desplegar el contracte.
    HotelPoints hpContract;
    
    event Log(address indexed sender, string message);

    // Constructor en que establim que l'owner(administrador) es qui desplega el contracte  
    constructor(HotelPoints tokenContract) {
        owner = msg.sender; 
        // nova variable (hpContract) que emmagatzema la direcció/instància del contracte ERC20. Aquesta variable ha d'inicialitzar-se a l'hora de desplegar el contracte.
        hpContract = tokenContract;
    }
     

    // Modifiers
    //Modifier que afegit a les capceleres de les funcions permet limitar quines funcions requereixen ser l'administrador
    //per cridar-les
    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    //Modifier que valida que el preu base d'un hotel no és zero
    modifier notZeroPrice(uint preuBase) {
         require(preuBase > 0,'El preu base ha de ser mes gran que zero');
        _;
    }

    //Modifier que valida que un hotel existeix o no  com a mapeig en funció del booleà existing
    modifier existingHotel(string memory newHotelName,bool existing) {
        if (existing)
            require(hotels[newHotelName].basePricePerDay>0,"No existeix cap hotel amb aquest nom" );          
        else 
           require(hotels[newHotelName].basePricePerDay==0,"Ja existeix un hotel amb aquest nom" );
        _;
    }

    //Modifier qye valida que la reserva té més de 0 dies.
    modifier notZeroDays(uint numDays) {
         require(numDays > 0,"El numero de dies de la reserva ha de ser mes gran que zero");
        _;
    }


    // Functions
    // Aquesta funció només pot ser executada per l'entitat administradora. Modificador OnlyOwner
    //Ha de comprovar que l'hotel no estigui ja registrat. Modificador existingHotel amb existing a false.
    //Ha de comprovar que el preu base especificat no sigui 0. Modificador notZeroPrice
    //és external perqué es cridable des del l'exterior pero no internament
    function registerHotel(string memory newHotelName, uint preuBase ) external onlyOwner notZeroPrice(preuBase) existingHotel(newHotelName,false) {

        Hotel storage newHotel = hotels[newHotelName];
        newHotel.basePricePerDay = preuBase;
        newHotel.registered = true;
               
    }

    //Aquesta funció es cridable per tothom però no internament. Tag external (menys costòs que pubic) 
    //Aquesta funció rep ether i ho indiquem amb el tag payable
    //Ha de comprovar que el nombre de dies de reserva especificat no sigui 0 i que l'hotel estigui registrat. Ja ho comproba la funció estimateBookingPrice a la que cridem
    //Per cada reserva realitzada, el contracte (ara propietari de tots els tokens) transfereix una quantitat de 5 tokens Hopos al client
     function bookHotel(string memory newHotelName,RoomType roomType, uint numDays) external payable {
        Reserva memory newReserva;
        uint price;

        
        newReserva.customer = msg.sender;
        newReserva.roomType = roomType;
        newReserva.bookingDays = numDays; 

        //Ha de comprovar que el Ether enviat es correspon amb el preu estipulat segons el preu base de l'hotel, el tipus d'habitació i els dies de reserva. 
        //Cridem directament la funció estimateBookingPrice(). 
        price = estimateBookingPrice(newHotelName, roomType,numDays);
        require(price==msg.value,string.concat("Cal enviar amb la reserva ",Strings.toString(price)," weis per a que es pugui formalitzar"));

        //La reserva s'emmagatzema en el array de reserves de l'hotel en qüestió. 
        hotels[newHotelName].bookings.push(newReserva);
           

        // Ara fem la transferència de 5 tokens del contracte Hotelpoints al compte de que ens crida per a fer la reserva. El contracte es el sender i el propietari dels fons
        hpContract.transfer(msg.sender,5);
    }

    
    //Es public perque és cridable per tothom i també internament i és view perque no modifica les variables d'estat
    //Ha de comprovar que el nombre de dies de reserva especificat no sigui 0 (amb el Modificador notZeroDays)
    //comproba que l'hotel estigui registrat amb el Modificador existingHotel amb existing a true.
    function estimateBookingPrice(string memory newHotelName,RoomType roomType, uint numDays) public view notZeroDays(numDays) existingHotel(newHotelName,true) returns (uint ){
        uint estimatedPrice=0;
        estimatedPrice= hotels[newHotelName].basePricePerDay*numDays;
        if (roomType == RoomType.Double)
            estimatedPrice= estimatedPrice *2;
        else {
            if (roomType == RoomType.Suite)
                estimatedPrice= estimatedPrice *3;
        }
        //La funció retorna el preu total de la reserva. DONE
       return estimatedPrice;
    }


    //Es external perqués cridable per tothom però no internament i és més "barat" que public" i és view perque no modifica les variables d'estat
    //comprobem que l'hotel estigui registrat amb el  modificador existingHotel amb existing a true.
    function getHotelBookings(string memory newHotelName) public  view existingHotel(newHotelName,true)  returns ( Reserva[] memory){
        //Ha de retornar un array d'objectes de reserva. DONE
        return hotels[newHotelName].bookings;

    }
  

    // Ejercicio 2 
    // La funció només ha de poder ser executada per l'entitat administradora
    // La fem external perqué gasti menys gas en no cridarse internament
    //transfereix tots els tokens del propietari del contracte HOtelPOints al contracte de l'Exercici 1.
    //Previament hem d'aprovar que el contracte HotelBookings pugui gastar tots els fons propietaris de l'owner de HotelPoints que és a qui el
    // constructor assigna inicialment els tokens. 
    function initializeHotelPoints() external onlyOwner{
         hpContract.transferFrom(owner,address(this),hpContract.totalSupply());
        
    }

}


/**
 * @title Ejercicio 2. Hotel points (ERC20 tokens) contract
 * @notice Do not use this contract in production
 */
 //Estenem el contacte de ERV20
contract HotelPoints is ERC20 {
    // Constructor
    // Variable que contindrà el total de tokens que s'emeten
    uint numTokens;
    //Propietari del contracte
    address public owner;

    // Modifiers
    //Modifier que afegit a les capceleres de les funcions permet limitar quines funcions requereixen ser l'administrador
    //per cridar-les
    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    //Tria el nom del token (Hopo) i el símbol (HP) que consideris.
    //El contracte farà una emissió de 10000 tokens al propietari del contracte en el moment d'inicialitzar-se.
    constructor() ERC20("Hopo", "HP") {
        numTokens=10000;
        
        owner = msg.sender; 
        //Fem l'emissió de tokens al propietari del contracte
        _mint(owner, numTokens);
     }


    // Utilitza 0 decimals per a representar els teus tokens ERC20. Coincideix l'enter de quantitat de tokens amb la seva representació
    //Fem un override de la funció de decimals 
    function decimals() public view virtual override returns (uint8) {
        return 0;
    }


}
