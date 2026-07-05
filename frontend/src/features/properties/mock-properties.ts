export interface Bed {
  id: string;
  name: string;
  status: "occupied" | "available" | "maintenance";
  currentOccupant?: string;
  rackRate: string;
  deposit: string;
  maintenanceIssue?: {
    id: string;
    issue: string;
    date: string;
    reporter: string;
  };
  history: Array<{
    resident: string;
    term: string;
    moveIn: string;
    moveOut: string;
    rate: string;
    initials: string;
  }>;
}

export interface Room {
  id: string;
  name: string;
  sharingType: "single" | "double" | "triple";
  category: "ac" | "non-ac";
  rent: string;
  occupiedBeds: number;
  totalBeds: number;
  amenities: string[];
  beds: Bed[];
}

export interface Floor {
  id: string;
  level: string; // e.g. "12", "11", "Penthouse"
  name: string;
  roomsCount: number;
  occupancyPercent: number;
  rooms: Room[];
}

export interface Property {
  id: string;
  name: string;
  type: string;
  address: string;
  city: string;
  state: string;
  pincode: string;
  totalFloors: number;
  totalRooms: number;
  occupancyPercent: number;
  images: string[];
  floors: Floor[];
}

// Initial mock property database
export const mockProperties: Property[] = [
  {
    id: "skyline",
    name: "Skyline Tower",
    type: "PG (Paying Guest)",
    address: "12, Outer Ring Road, Bellandur",
    city: "Bengaluru",
    state: "Karnataka",
    pincode: "560103",
    totalFloors: 12,
    totalRooms: 288,
    occupancyPercent: 92,
    images: [
      "https://lh3.googleusercontent.com/aida-public/AB6AXuCnV0AJ8slF7JjAp8PJekjnXhEtthqLzdlMso6N4J5jHg2EIcK-rskIQmWRDQtRy2ctUL6I70fHtRXGxFvYB8G9jGHhajzCvgsqo5-39FfmgKft7cBB7UtH4i54ClbsvIj5xpiso6jYXAQtCLjpTXl6q187pNrqdGprjgbmulxPl1trnu9eAUpWRdd1PdaLxiVFD8X2o3nJ19eGN0VA_nJXtpYDPDArthRl1aNQCyVVByqgiL4HdQS68g",
      "https://lh3.googleusercontent.com/aida-public/AB6AXuB94TQH7EDXhHmW1uunSUr95qrT_4Yah6Hm1jrd2s8sYSrWApFzSvbVhKEiiXrVYc04krZpnIbEurlQc7eofmYU_wWHqjLTEz4R53gvtEsmrOIoAUzbMzmYsSKTdgSz1RXQaVb-8QnfqHH51K4rPP5Zwy_0g4atVuKHilJ2hwms22fidX6SFsanzg5cpVW0luTToHBaQz9eTTOHL5J_i1YNnc0LUu3yIedaZiDjGfle8lE-I8mNAx7DFQ"
    ],
    floors: [
      {
        id: "12",
        level: "12",
        name: "Penthouse Level",
        roomsCount: 4,
        occupancyPercent: 100,
        rooms: [
          {
            id: "1201",
            name: "1201-A",
            sharingType: "single",
            category: "ac",
            rent: "₹1200.00",
            occupiedBeds: 1,
            totalBeds: 1,
            amenities: ["Wi-Fi", "Cleaning", "Laundry"],
            beds: [
              {
                id: "A",
                name: "Bed A",
                status: "occupied",
                currentOccupant: "Alex Johnson",
                rackRate: "₹1200.00",
                deposit: "₹600.00",
                history: [
                  { resident: "Alex Johnson", term: "Yearly '24", moveIn: "01/15/24", moveOut: "--", rate: "₹1200", initials: "AJ" }
                ]
              }
            ]
          }
        ]
      },
      {
        id: "11",
        level: "11",
        name: "Floor 11",
        roomsCount: 24,
        occupancyPercent: 95,
        rooms: []
      },
      {
        id: "10",
        level: "10",
        name: "Floor 10",
        roomsCount: 24,
        occupancyPercent: 75,
        rooms: []
      },
      {
        id: "9",
        level: "9",
        name: "Floor 9",
        roomsCount: 24,
        occupancyPercent: 90,
        rooms: []
      },
      {
        id: "4",
        level: "4",
        name: "Floor 4",
        roomsCount: 16,
        occupancyPercent: 50,
        rooms: [
          {
            id: "402",
            name: "402",
            sharingType: "double",
            category: "ac",
            rent: "₹850.00",
            occupiedBeds: 1,
            totalBeds: 2,
            amenities: ["Wi-Fi", "Cleaning", "Laundry"],
            beds: [
              {
                id: "A",
                name: "Bed A",
                status: "occupied",
                currentOccupant: "Alex Smith",
                rackRate: "₹850.00",
                deposit: "₹400.00",
                history: [
                  { resident: "Alex Smith", term: "Fall Semester '23", moveIn: "08/15/23", moveOut: "--", rate: "₹850", initials: "AS" }
                ]
              },
              {
                id: "B",
                name: "Bed B",
                status: "maintenance",
                rackRate: "₹850.00",
                deposit: "₹400.00",
                maintenanceIssue: {
                  id: "WO-4921",
                  issue: "Reported broken bed frame slat. Scheduled for repair by internal team on 10/24/2023.",
                  date: "10/21/2023",
                  reporter: "Staff (J. Doe)"
                },
                history: [
                  { resident: "Alex Smith", term: "Fall Semester '23", moveIn: "08/15/23", moveOut: "10/20/23 (Early)", rate: "₹850", initials: "AS" },
                  { resident: "Maria Johnson", term: "Spring Semester '23", moveIn: "01/10/23", moveOut: "05/30/23", rate: "₹825", initials: "MJ" },
                  { resident: "David Torres", term: "Fall Semester '22", moveIn: "08/12/22", moveOut: "12/15/22", rate: "₹800", initials: "DT" }
                ]
              }
            ]
          }
        ]
      }
    ]
  },
  {
    id: "sunset",
    name: "Sunset Apartments Complex",
    type: "Apartment",
    address: "Block B, Sunset Hills",
    city: "Mumbai",
    state: "Maharashtra",
    pincode: "400001",
    totalFloors: 5,
    totalRooms: 60,
    occupancyPercent: 88,
    images: [],
    floors: []
  }
];
