export type PhotoSlot = {id: string; label: string; instruction: string};
export const photoSlots: Record<'claims'|'underwriting', PhotoSlot[]> = {
  claims: [
    {id:'vehicle_overview',label:'Vehicle overview',instruction:'Show the passenger vehicle clearly. Example: the whole car from one corner.'},
    {id:'front_registration',label:'Front registration view',instruction:'Show a sharp, readable plate mounted on the front of the vehicle, with surrounding bodywork.'},
    {id:'damage_overview',label:'Damage overview',instruction:'Show the car or relevant area with surrounding vehicle panels. Visible damage is not required to upload; it is assessed later.'},
    {id:'damage_closeup',label:'Damage close-up',instruction:'Show a recognizable car part or a clear car photograph. Undamaged parts are accepted; visible damage is assessed later.'},
  ],
  underwriting: [
    {id:'front_left',label:'Front left',instruction:'Show the front and left side of the passenger vehicle.'},
    {id:'front_right',label:'Front right',instruction:'Show the front and right side of the passenger vehicle.'},
    {id:'rear_left',label:'Rear left',instruction:'Show the rear and left side of the passenger vehicle.'},
    {id:'rear_right',label:'Rear right',instruction:'Show the rear and right side of the passenger vehicle.'},
    {id:'odometer',label:'Odometer',instruction:'Show a sharp, readable mileage display in the dashboard, with instrument-cluster context.'},
    {id:'registration_plate',label:'Registration plate',instruction:'Show a readable vehicle-mounted plate with surrounding bodywork.'},
  ],
};
