#include<iostream>
using namespace std;

int main() {
    int s; cin >> s;
    if(s == 1)
        cout << "2 -1\n";
    else if(s == -999)
        cout << "-998 -1\n";
    else
        cout << s - 1 << " 1\n";
}
